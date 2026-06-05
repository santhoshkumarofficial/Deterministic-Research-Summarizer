-- ================================================================
--  ResearchAI  —  MySQL Schema  (JWT auth, no user_sessions table)
--  Run: mysql -u <user> -p research_ai < schema.sql
-- ================================================================

CREATE TABLE IF NOT EXISTS users (
    id            VARCHAR(36)  NOT NULL PRIMARY KEY,
    username      VARCHAR(80)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name  VARCHAR(120) NOT NULL DEFAULT '',
    last_seen     DATETIME     NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Stores the full pipeline output JSON for each processed paper
CREATE TABLE IF NOT EXISTS job_outputs (
    job_id      VARCHAR(36)  NOT NULL PRIMARY KEY,
    user_id     VARCHAR(36)  NOT NULL,
    filename    VARCHAR(255) NOT NULL,
    stem        VARCHAR(255) NOT NULL,
    output_json LONGTEXT     NOT NULL,   -- full output dict as JSON string
    output_path VARCHAR(512) NOT NULL DEFAULT '',
    report_path VARCHAR(512) NOT NULL DEFAULT '',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_jo_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Each chat session links a user to one processed paper
CREATE TABLE IF NOT EXISTS chat_sessions (
    id         VARCHAR(36)  NOT NULL PRIMARY KEY,
    user_id    VARCHAR(36)  NOT NULL,
    job_id     VARCHAR(36)  NOT NULL,
    name       VARCHAR(255) NOT NULL DEFAULT 'New Chat',
    filename   VARCHAR(255) NOT NULL DEFAULT '',
    updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_cs_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_cs_job  FOREIGN KEY (job_id)  REFERENCES job_outputs (job_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Chat messages (user + assistant turns)
CREATE TABLE IF NOT EXISTS messages (
    id         VARCHAR(36)  NOT NULL PRIMARY KEY,
    session_id VARCHAR(36)  NOT NULL,
    role       ENUM('user','assistant','system') NOT NULL DEFAULT 'user',
    content    LONGTEXT     NOT NULL,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_msg_session FOREIGN KEY (session_id) REFERENCES chat_sessions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Useful indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_jo_user      ON job_outputs    (user_id);
CREATE INDEX IF NOT EXISTS idx_cs_user      ON chat_sessions  (user_id);
CREATE INDEX IF NOT EXISTS idx_cs_updated   ON chat_sessions  (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_msg_session  ON messages       (session_id, created_at ASC);