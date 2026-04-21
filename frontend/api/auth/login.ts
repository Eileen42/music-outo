import type { VercelRequest, VercelResponse } from '@vercel/node'
import { neon } from '@neondatabase/serverless'
import crypto from 'crypto'

const sql = neon(process.env.DATABASE_URL!)

function verifyPassword(password: string, stored: string): boolean {
  const [salt, hash] = stored.split(':')
  const verifyHash = crypto.scryptSync(password, salt, 64).toString('hex')
  return hash === verifyHash
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  try {
    const { email, password } = req.body || {}

    if (!email || !password) {
      return res.status(400).json({ error: '이메일과 비밀번호를 입력해주세요' })
    }

    const rows = await sql`SELECT id, name, token, status, password_hash FROM users WHERE email = ${email}`
    if (rows.length === 0) {
      return res.status(401).json({ error: '이메일 또는 비밀번호가 올바르지 않습니다' })
    }

    const user = rows[0]

    // 비밀번호가 아직 없는 기존 사용자 (마이그레이션 전 가입자)
    if (!user.password_hash) {
      return res.status(401).json({ error: '비밀번호가 설정되지 않은 계정입니다. 관리자에게 문의해주세요.' })
    }

    if (!verifyPassword(password, user.password_hash)) {
      return res.status(401).json({ error: '이메일 또는 비밀번호가 올바르지 않습니다' })
    }

    return res.status(200).json({
      token: user.token,
      name: user.name,
      status: user.status,
    })
  } catch (err) {
    console.error('[login]', err)
    const message = err instanceof Error ? err.message : String(err)
    return res.status(500).json({ error: `서버 오류: ${message}` })
  }
}
