import type { VercelRequest, VercelResponse } from '@vercel/node'
import { neon } from '@neondatabase/serverless'

const sql = neon(process.env.DATABASE_URL!)

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  const token = req.query.token as string
  if (!token) {
    return res.status(400).json({ error: '토큰이 필요합니다' })
  }

  const rows = await sql`SELECT id, name, email, status FROM users WHERE token = ${token}`
  if (rows.length === 0) {
    return res.status(404).json({ error: '사용자를 찾을 수 없습니다', status: 'not_found' })
  }

  const user = rows[0]
  return res.status(200).json({
    id: user.id,
    name: user.name,
    email: user.email,
    status: user.status,
  })
}
