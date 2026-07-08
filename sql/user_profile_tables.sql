-- 用户资料表（存储基本信息、职业背景、技能等）
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nickname VARCHAR(50),
    occupation VARCHAR(100),
    industry VARCHAR(50),           -- IT/金融/医疗/教育/制造/其他
    experience_years VARCHAR(20),   -- 应届/1-3年/3-5年/5-10年/10年以上
    skills TEXT[],                  -- 技能标签数组
    bio TEXT,                       -- 个人简介（最大500字）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id)                 -- 每个用户只有一条资料记录
);

-- 用户上传文档表（简历、作品集等）
CREATE TABLE IF NOT EXISTS user_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(20),          -- PDF/DOCX/TXT
    file_size INTEGER,              -- 文件大小(bytes)
    file_content BYTEA,             -- 原始文件二进制内容（用于异步解析）
    parsed_text TEXT,               -- 解析后的文本内容
    parse_status VARCHAR(20) DEFAULT 'completed',  -- uploading/parsing/completed/failed
    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_documents_user_id ON user_documents(user_id);