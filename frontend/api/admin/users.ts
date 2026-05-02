import type { VercelRequest, VercelResponse } from '@vercel/node'
import { neon } from '@neondatabase/serverless'

const sql = neon(process.env.DATABASE_URL!)

function isAdmin(req: VercelRequest): boolean {
  const expected = process.env.ADMIN_SECRET
  if (!expected) return false
  const auth = req.headers.authorization
  return auth === `Bearer ${expected}`
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (!process.env.ADMIN_SECRET) {
    return res.status(503).json({ error: 'ADMIN_SECRET 환경변수가 설정되지 않았습니다' })
  }
  if (!isAdmin(req)) {
    return res.status(403).json({ error: '권한이 없습니다' })
  }

  if (req.method === 'GET') {
    const status = req.query.status as string | undefined
    let rows
    if (status) {
      rows = await sql`
        SELECT id, name, email, phone, referral_source, status, created_at, approved_at
        FROM users WHERE status = ${status}
        ORDER BY created_at DESC
      `
    } else {
      rows = await sql`
        SELECT id, name, email, phone, referral_source, status, created_at, approved_at
        FROM users ORDER BY created_at DESC
      `
    }
    return res.status(200).json({ users: rows })
  }

  return res.status(405).json({ error: 'Method not allowed' })
}
