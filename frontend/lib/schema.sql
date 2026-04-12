-- Neon Postgres 초기 스키마
-- Neon Dashboard SQL Editor에서 실행하세요

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(255) UNIQUE NOT NULL,
  phone VARCHAR(50),
  referral_source VARCHAR(200),
  status VARCHAR(20) DEFAULT 'pending',
  token VARCHAR(255) UNIQUE NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  approved_at TIMESTAMP
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_users_token ON users(token);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
