import type { VercelRequest, VercelResponse } from '@vercel/node'
import { neon } from '@neondatabase/serverless'
import crypto from 'crypto'

const sql = neon(process.env.DATABASE_URL!)

const ADMIN_SECRET = process.env.ADMIN_SECRET || 'admin-default-secret'

function isAdmin(req: VercelRequest): boolean {
  const auth = req.headers.authorization
  return auth === `Bearer ${ADMIN_SECRET}`
}

function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16).toString('hex')
  const hash = crypto.scryptSync(password, salt, 64).toString('hex')
  return `${salt}:${hash}`
}

// 관리자가 사용자 비밀번호를 랜덤 임시값으로 초기화.
// 응답의 temporary_password 는 한 번만 보여주고(DB엔 해시만 저장됨)
// 관리자가 사용자에게 카톡·문자 등으로 전달한다.
export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (!isAdmin(req)) {
    return res.status(403).json({ error: '권한이 없습니다' })
  }
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  try {
    const { user_id } = req.body || {}
    if (!user_id) {
      return res.status(400).json({ error: 'user_id 가 필요합니다' })
    }

    // 8자 영숫자 (사용자가 치기 편하도록 헷갈리는 0O1l 제외)
    const tempPassword = crypto.randomBytes(6)
      .toString('base64')
      .replace(/[+/=]/g, '')
      .replace(/[0O1lI]/g, 'x')
      .slice(0, 8)

    const passwordHash = hashPassword(tempPassword)

    const rows = await sql`
      UPDATE users SET password_hash = ${passwordHash}
      WHERE id = ${Number(user_id)}
      RETURNING email, name
    `
    if (rows.length === 0) {
      return res.status(404).json({ error: '해당 사용자를 찾을 수 없습니다' })
    }

    return res.status(200).json({
      message: '비밀번호가 임시값으로 초기화되었습니다',
      email: rows[0].email,
      name: rows[0].name,
      temporary_password: tempPassword,
    })
  } catch (err) {
    console.error('[reset-password]', err)
    const message = err instanceof Error ? err.message : String(err)
    return res.status(500).json({ error: `서버 오류: ${message}` })
  }
}
