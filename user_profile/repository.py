"""用户资料与文档数据库仓库层"""
import uuid
import threading
from datetime import datetime
from typing import Optional, List
import psycopg2
from psycopg2.extras import RealDictCursor

from config.database import DatabaseConfig
from utils.logger import logger
from conversation.repository import _ensure_utc_iso, _get_connection, _release_connection


class UserProfileRepository:
    """用户资料仓库"""

    def get_profile(self, user_id: str) -> Optional[dict]:
        """
        获取用户资料

        Args:
            user_id: 用户ID

        Returns:
            dict | None: 用户资料字典
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, user_id, nickname, occupation, industry,
                           experience_years, skills, bio, created_at, updated_at
                    FROM user_profiles
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()

            if row is None:
                return None

            return {
                "id": str(row["id"]),
                "user_id": str(row["user_id"]),
                "nickname": row["nickname"],
                "occupation": row["occupation"],
                "industry": row["industry"],
                "experience_years": row["experience_years"],
                "skills": row["skills"] or [],
                "bio": row["bio"],
                "created_at": _ensure_utc_iso(row["created_at"]),
                "updated_at": _ensure_utc_iso(row["updated_at"]),
            }

        except psycopg2.Error as e:
            logger.error(f"获取用户资料失败: user_id={user_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def create_or_update_profile(
        self,
        user_id: str,
        nickname: Optional[str] = None,
        occupation: Optional[str] = None,
        industry: Optional[str] = None,
        experience_years: Optional[str] = None,
        skills: Optional[List[str]] = None,
        bio: Optional[str] = None,
    ) -> dict:
        """
        创建或更新用户资料（使用UPSERT）

        Args:
            user_id: 用户ID
            nickname: 昵称
            occupation: 职业/岗位
            industry: 行业领域
            experience_years: 工作年限
            skills: 技能标签列表
            bio: 个人简介

        Returns:
            dict: 更新后的用户资料
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO user_profiles (user_id, nickname, occupation, industry,
                                              experience_years, skills, bio, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                        nickname = EXCLUDED.nickname,
                        occupation = EXCLUDED.occupation,
                        industry = EXCLUDED.industry,
                        experience_years = EXCLUDED.experience_years,
                        skills = EXCLUDED.skills,
                        bio = EXCLUDED.bio,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id, user_id, nickname, occupation, industry,
                              experience_years, skills, bio, created_at, updated_at
                    """,
                    (user_id, nickname, occupation, industry, experience_years, skills, bio),
                )
                row = cur.fetchone()
                conn.commit()

            logger.info(f"用户资料已保存: user_id={user_id}")
            return {
                "id": str(row["id"]),
                "user_id": str(row["user_id"]),
                "nickname": row["nickname"],
                "occupation": row["occupation"],
                "industry": row["industry"],
                "experience_years": row["experience_years"],
                "skills": row["skills"] or [],
                "bio": row["bio"],
                "created_at": _ensure_utc_iso(row["created_at"]),
                "updated_at": _ensure_utc_iso(row["updated_at"]),
            }

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"保存用户资料失败: user_id={user_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)


class UserDocumentRepository:
    """用户文档仓库"""

    def list_documents(self, user_id: str) -> List[dict]:
        """
        获取用户上传的文档列表

        Args:
            user_id: 用户ID

        Returns:
            list[dict]: 文档列表
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, user_id, filename, file_type, file_size,
                           parsed_text, parse_status, upload_time
                    FROM user_documents
                    WHERE user_id = %s
                    ORDER BY upload_time DESC
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()

            return [
                {
                    "id": str(row["id"]),
                    "user_id": str(row["user_id"]),
                    "filename": row["filename"],
                    "file_type": row["file_type"],
                    "file_size": row["file_size"],
                    "parsed_text": row["parsed_text"],
                    "parse_status": row["parse_status"] or "completed",
                    "upload_time": _ensure_utc_iso(row["upload_time"]),
                }
                for row in rows
            ]

        except psycopg2.Error as e:
            logger.error(f"获取文档列表失败: user_id={user_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def create_document(
        self,
        user_id: str,
        filename: str,
        file_type: str,
        file_size: int,
        file_content: bytes,
        parsed_text: Optional[str] = None,
    ) -> dict:
        """
        创建文档记录（支持异步解析：先保存原始内容和初始状态，解析完成后更新parsed_text）

        Args:
            user_id: 用户ID
            filename: 文件名
            file_type: 文件类型(PDF/DOCX/TXT)
            file_size: 文件大小(bytes)
            file_content: 原始文件二进制内容
            parsed_text: 解析后的文本（如果同步解析则传入，异步解析则None）

        Returns:
            dict: 文档信息
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 如果有解析文本，状态为completed；否则为uploading（异步解析）
                if parsed_text:
                    cur.execute(
                        """
                        INSERT INTO user_documents (user_id, filename, file_type, file_size, file_content, parsed_text, parse_status)
                        VALUES (%s, %s, %s, %s, %s, %s, 'completed')
                        RETURNING id, user_id, filename, file_type, file_size, file_content, parsed_text, parse_status, upload_time
                        """,
                        (user_id, filename, file_type, file_size, psycopg2.Binary(file_content), parsed_text),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO user_documents (user_id, filename, file_type, file_size, file_content, parse_status)
                        VALUES (%s, %s, %s, %s, %s, 'uploading')
                        RETURNING id, user_id, filename, file_type, file_size, file_content, parsed_text, parse_status, upload_time
                        """,
                        (user_id, filename, file_type, file_size, psycopg2.Binary(file_content)),
                    )
                row = cur.fetchone()
                conn.commit()

            logger.info(f"文档已上传: user_id={user_id}, filename={filename}, parse_status={row['parse_status']}")
            return {
                "id": str(row["id"]),
                "user_id": str(row["user_id"]),
                "filename": row["filename"],
                "file_type": row["file_type"],
                "file_size": row["file_size"],
                "parsed_text": row["parsed_text"],
                "parse_status": row["parse_status"] or "completed",
                "upload_time": _ensure_utc_iso(row["upload_time"]),
            }

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"创建文档记录失败: user_id={user_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def get_document_by_id(self, document_id: str, user_id: str) -> Optional[dict]:
        """
        根据ID获取文档信息

        Args:
            document_id: 文档ID
            user_id: 用户ID（用于验证归属）

        Returns:
            dict | None: 文档信息
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, user_id, filename, file_type, file_size,
                           parsed_text, parse_status, upload_time
                    FROM user_documents
                    WHERE id = %s AND user_id = %s
                    """,
                    (document_id, user_id),
                )
                row = cur.fetchone()

            if row is None:
                return None

            return {
                "id": str(row["id"]),
                "user_id": str(row["user_id"]),
                "filename": row["filename"],
                "file_type": row["file_type"],
                "file_size": row["file_size"],
                "parsed_text": row["parsed_text"],
                "parse_status": row["parse_status"] or "completed",
                "upload_time": _ensure_utc_iso(row["upload_time"]),
            }

        except psycopg2.Error as e:
            logger.error(f"获取文档失败: id={document_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def update_parse_status(self, document_id: str, status: str):
        """
        更新文档解析状态

        Args:
            document_id: 文档ID
            status: 状态 (uploading/parsing/completed/failed)
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE user_documents SET parse_status = %s WHERE id = %s
                    """,
                    (status, document_id),
                )
                conn.commit()
            logger.debug(f"文档解析状态已更新: id={document_id}, status={status}")
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"更新解析状态失败: id={document_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def update_parsed_text(self, document_id: str, parsed_text: str, status: str = "completed"):
        """
        更新文档解析文本和状态

        Args:
            document_id: 文档ID
            parsed_text: 解析后的文本
            status: 最终状态 (completed/failed)
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE user_documents SET parsed_text = %s, parse_status = %s WHERE id = %s
                    """,
                    (parsed_text, status, document_id),
                )
                conn.commit()
            logger.info(f"文档解析完成: id={document_id}, status={status}, text_len={len(parsed_text)}")
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"更新解析文本失败: id={document_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def get_document_status(self, document_id: str, user_id: str) -> Optional[dict]:
        """
        获取文档解析状态

        Args:
            document_id: 文档ID
            user_id: 用户ID

        Returns:
            dict | None: 包含状态信息的字典
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, filename, parse_status, file_type, file_size, upload_time
                    FROM user_documents
                    WHERE id = %s AND user_id = %s
                    """,
                    (document_id, user_id),
                )
                row = cur.fetchone()

            if row is None:
                return None

            return {
                "id": str(row["id"]),
                "filename": row["filename"],
                "file_type": row["file_type"],
                "file_size": row["file_size"],
                "parse_status": row["parse_status"] or "completed",
                "upload_time": _ensure_utc_iso(row["upload_time"]),
            }

        except psycopg2.Error as e:
            logger.error(f"获取文档状态失败: id={document_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def delete_document(self, document_id: str, user_id: str) -> bool:
        """
        删除文档记录

        Args:
            document_id: 文档ID
            user_id: 用户ID（用于验证归属）

        Returns:
            bool: 是否删除成功
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM user_documents
                    WHERE id = %s AND user_id = %s
                    """,
                    (document_id, user_id),
                )
                deleted = cur.rowcount > 0
                conn.commit()

            if deleted:
                logger.info(f"文档已删除: id={document_id}")
            return deleted

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"删除文档失败: id={document_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def get_user_parsed_texts(self, user_id: str) -> List[str]:
        """
        获取用户所有已解析完成的文档文本（用于拼接system message）

        Args:
            user_id: 用户ID

        Returns:
            list[str]: 解析文本列表（仅包含parse_status='completed'的文档）
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT parsed_text FROM user_documents
                    WHERE user_id = %s AND parse_status = 'completed' AND parsed_text IS NOT NULL
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()

            return [row[0] for row in rows if row[0]]

        except psycopg2.Error as e:
            logger.error(f"获取用户解析文本失败: user_id={user_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)


# 单例实例
_user_profile_repo = None
_user_document_repo = None


def get_user_profile_repo() -> UserProfileRepository:
    """获取用户资料仓库单例"""
    global _user_profile_repo
    if _user_profile_repo is None:
        _user_profile_repo = UserProfileRepository()
    return _user_profile_repo


def get_user_document_repo() -> UserDocumentRepository:
    """获取用户文档仓库单例"""
    global _user_document_repo
    if _user_document_repo is None:
        _user_document_repo = UserDocumentRepository()
    return _user_document_repo


def _async_parse_worker(document_id: str, user_id: str):
    """
    后台异步解析文档的工作线程

    Args:
        document_id: 文档ID
        user_id: 用户ID
    """
    import psycopg2
    from user_profile.document_parser import parse_document

    repo = get_user_document_repo()
    conn = None
    try:
        # 1. 更新状态为 parsing
        repo.update_parse_status(document_id, "parsing")

        # 2. 读取原始文件内容
        conn = _get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT file_content, file_type FROM user_documents
                WHERE id = %s AND user_id = %s
                """,
                (document_id, user_id),
            )
            row = cur.fetchone()
        if not row or not row[0]:
            raise ValueError("文件内容不存在或已删除")
        file_content = bytes(row[0])
        file_type = row[1]

        # 3. 解析文档
        logger.info(f"开始异步解析文档: id={document_id}, type={file_type}")
        parsed_text = parse_document(file_content, file_type)

        # 4. 更新解析结果
        repo.update_parsed_text(document_id, parsed_text, "completed")
        logger.info(f"文档异步解析完成: id={document_id}, text_len={len(parsed_text)}")

    except Exception as e:
        logger.error(f"文档异步解析失败: id={document_id}, error={e}")
        try:
            repo.update_parsed_text(document_id, f"解析失败: {str(e)}", "failed")
        except Exception:
            pass
    finally:
        if conn:
            _release_connection(conn)


def start_async_parse(document_id: str, user_id: str):
    """
    启动异步文档解析（在后台线程中执行）

    Args:
        document_id: 文档ID
        user_id: 用户ID
    """
    thread = threading.Thread(
        target=_async_parse_worker,
        args=(document_id, user_id),
        daemon=True,
        name=f"async-parse-{document_id[:8]}",
    )
    thread.start()
    logger.info(f"异步解析线程已启动: id={document_id}")