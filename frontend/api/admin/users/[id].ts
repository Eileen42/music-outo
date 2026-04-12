import type { VercelRequest, VercelResponse } from '@vercel/node'
import { neon } from '@neondatabase/serverless'

const sql = neon(process.env.DATABASE_URL!)

const ADMIN_SECRET = process.env.ADMIN_SECRET || 'admin-default-secret'

function isAdmin(req: VercelRequest): boolean {
  const auth = req.headers.authorization
  return auth === `Bearer ${ADMIN_SECRET}`
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (!isAdmin(req)) {
    return res.status(403).json({ error: '권한이 없습니다' })
  }

  if (req.method !== 'PATCH') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  const { id } = req.query
  const { status } = req.body || {}

  if (!status || !['approved', 'rejected', 'blocked', 'pending'].includes(status)) {
    return res.status(400).json({ error: '유효한 상태값이 필요합니다 (approved/rejected/blocked/pending)' })
  }

  const approvedAt = status === 'approved' ? new Date().toISOString() : null

  await sql`
    UPDATE users SET status = ${status}, approved_at = ${approvedAt}
    WHERE id = ${Number(id)}
  `

  return res.status(200).json({ message: '상태가 변경되었습니다', id: Number(id), status })
}
