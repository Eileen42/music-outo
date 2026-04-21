import type { VercelRequest, VercelResponse } from '@vercel/node'
import { neon } from '@neondatabase/serverless'
import crypto from 'crypto'

const sql = neon(process.env.DATABASE_URL!)

function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16).toString('hex')
  const hash = crypto.scryptSync(password, salt, 64).toString('hex')
  return `${salt}:${hash}`
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  try {
    const { email, code, new_password } = req.body || {}

    if (!email || !code || !new_password) {
      return res.status(400).json({ error: '이메일, 인증번호, 새 비밀번호 모두 필요합니다' })
    }
    if (new_password.length < 4) {
      return res.status(400).json({ error: '비밀번호는 4자 이상이어야 합니다' })
    }

    const rows = await sql`
      SELECT id, reset_code, reset_code_expires_at
      FROM users
      WHERE email = ${email}
    `

    if (rows.length === 0) {
      // 존재 노출 방지 위해 실패 메시지는 일관되게
      return res.status(400).json({ error: '이메일 또는 인증번호가 올바르지 않습니다' })
    }

    const user = rows[0]
    if (!user.reset_code || user.reset_code !== String(code)) {
      return res.status(400).json({ error: '이메일 또는 인증번호가 올바르지 않습니다' })
    }

    const expiresAt = user.reset_code_expires_at ? new Date(user.reset_code_expires_at) : null
    if (!expiresAt || expiresAt.getTime() < Date.now()) {
      return res.status(400).json({ error: '인증번호가 만료되었습니다. 다시 요청해주세요.' })
    }

    const passwordHash = hashPassword(new_password)

    // 비번 교체하고 사용된 인증번호는 즉시 무효화
    await sql`
      UPDATE users
      SET password_hash = ${passwordHash},
          reset_code = NULL,
          reset_code_expires_at = NULL
      WHERE id = ${user.id}
    `

    return res.status(200).json({ message: '비밀번호가 변경되었습니다. 새 비밀번호로 로그인해주세요.' })
  } catch (err) {
    console.error('[reset-password]', err)
    const message = err instanceof Error ? err.message : String(err)
    return res.status(500).json({ error: `서버 오류: ${message}` })
  }
}
