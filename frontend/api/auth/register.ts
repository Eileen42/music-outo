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
    const { name, email, phone, referral_source, password } = req.body || {}

    if (!name || !email || !password) {
      return res.status(400).json({ error: '이름, 이메일, 비밀번호는 필수입니다' })
    }

    if (password.length < 4) {
      return res.status(400).json({ error: '비밀번호는 4자 이상이어야 합니다' })
    }

    // 이메일 중복 체크
    const existing = await sql`SELECT id, token, status FROM users WHERE email = ${email}`
    if (existing.length > 0) {
      return res.status(409).json({ error: '이미 가입된 이메일입니다. 로그인해주세요.' })
    }

    const token = crypto.randomUUID()
    const passwordHash = hashPassword(password)

    await sql`
      INSERT INTO users (name, email, phone, referral_source, token, status, password_hash)
      VALUES (${name}, ${email}, ${phone || null}, ${referral_source || null}, ${token}, 'pending', ${passwordHash})
    `

    return res.status(201).json({
      token,
      status: 'pending',
      message: '가입 신청이 완료되었습니다. 관리자 승인을 기다려주세요.',
    })
  } catch (err) {
    // DB 연결/쿼리 실패 등 예상치 못한 예외도 JSON 으로 돌려줘야 프론트에서
    // "가입 중 오류가 발생했습니다" fallback 이 아닌 실제 원인을 보여줄 수 있다
    console.error('[register]', err)
    const message = err instanceof Error ? err.message : String(err)
    return res.status(500).json({ error: `서버 오류: ${message}` })
  }
}
