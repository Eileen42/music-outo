import type { VercelRequest, VercelResponse } from '@vercel/node'
import { neon } from '@neondatabase/serverless'
import { Resend } from 'resend'
import crypto from 'crypto'

const sql = neon(process.env.DATABASE_URL!)
const resend = new Resend(process.env.RESEND_API_KEY || '')

// 인증번호 관련 컬럼이 없으면 추가 (idempotent — 여러 번 실행돼도 안전)
let schemaReady = false
async function ensureSchema() {
  if (schemaReady) return
  await sql`ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_code TEXT`
  await sql`ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_code_expires_at TIMESTAMPTZ`
  schemaReady = true
}

function generateCode(): string {
  // 6자리 숫자 (000000~999999)
  return crypto.randomInt(0, 1_000_000).toString().padStart(6, '0')
}

function emailHtml(name: string, code: string): string {
  return `
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 24px; background: #0f172a; color: #e5e7eb;">
      <h2 style="color: #a855f7; margin: 0 0 16px;">🎬 Music Outo 비밀번호 재설정</h2>
      <p style="margin: 0 0 24px;">안녕하세요 <strong style="color: #fff;">${name}</strong> 님,</p>
      <p style="margin: 0 0 16px;">비밀번호 재설정 인증번호입니다. 앱의 비밀번호 재설정 화면에 입력해주세요.</p>
      <div style="background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin: 24px 0; text-align: center;">
        <div style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #a855f7; font-family: monospace;">${code}</div>
      </div>
      <p style="margin: 0 0 8px; color: #94a3b8; font-size: 13px;">⏰ 이 인증번호는 <strong>10분 후 만료</strong>됩니다.</p>
      <p style="margin: 0; color: #94a3b8; font-size: 13px;">본인이 요청하지 않았다면 이 메일을 무시해주세요. 계정 비밀번호는 변경되지 않습니다.</p>
    </div>
  `
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  try {
    if (!process.env.RESEND_API_KEY) {
      return res.status(500).json({ error: '이메일 서비스가 설정되지 않았습니다' })
    }

    const { email } = req.body || {}
    if (!email) {
      return res.status(400).json({ error: '이메일을 입력해주세요' })
    }

    await ensureSchema()

    const rows = await sql`SELECT id, name, email FROM users WHERE email = ${email}`

    // 보안: 존재 여부를 노출하지 않기 위해 성공 응답은 동일하게 반환
    if (rows.length === 0) {
      return res.status(200).json({
        message: '이메일이 가입된 계정이면 인증번호가 발송됩니다. 1~2분 안에 도착하지 않으면 스팸함을 확인해주세요.',
      })
    }

    const user = rows[0]
    const code = generateCode()
    const expiresAt = new Date(Date.now() + 10 * 60 * 1000).toISOString() // 10분 뒤

    await sql`
      UPDATE users
      SET reset_code = ${code}, reset_code_expires_at = ${expiresAt}
      WHERE id = ${user.id}
    `

    const result = await resend.emails.send({
      from: 'Music Outo <onboarding@resend.dev>',
      to: user.email,
      subject: '[Music Outo] 비밀번호 재설정 인증번호',
      html: emailHtml(user.name, code),
    })

    if (result.error) {
      console.error('[forgot-password] resend error', result.error)
      return res.status(500).json({
        error: `이메일 발송 실패: ${result.error.message || '알 수 없는 오류'}`,
      })
    }

    return res.status(200).json({
      message: '이메일이 가입된 계정이면 인증번호가 발송됩니다. 1~2분 안에 도착하지 않으면 스팸함을 확인해주세요.',
    })
  } catch (err) {
    console.error('[forgot-password]', err)
    const message = err instanceof Error ? err.message : String(err)
    return res.status(500).json({ error: `서버 오류: ${message}` })
  }
}
