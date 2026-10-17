"""FTS5 full-text index over knowledge chunks and posts

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE VIRTUAL TABLE knowledge_fts USING fts5(heading, text, content='knowledge_chunks', "
        "content_rowid='id', tokenize='porter unicode61')"
    )
    op.execute(
        "CREATE TRIGGER knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN "
        "INSERT INTO knowledge_fts(rowid, heading, text) VALUES (new.id, new.heading, new.text); END"
    )
    op.execute(
        "CREATE TRIGGER knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN "
        "INSERT INTO knowledge_fts(knowledge_fts, rowid, heading, text) VALUES ('delete', old.id, old.heading, old.text); END"
    )
    op.execute(
        "CREATE TRIGGER knowledge_chunks_au AFTER UPDATE ON knowledge_chunks BEGIN "
        "INSERT INTO knowledge_fts(knowledge_fts, rowid, heading, text) VALUES ('delete', old.id, old.heading, old.text); "
        "INSERT INTO knowledge_fts(rowid, heading, text) VALUES (new.id, new.heading, new.text); END"
    )
    op.execute(
        "CREATE VIRTUAL TABLE posts_fts USING fts5(title, body, content='posts', content_rowid='id', "
        "tokenize='porter unicode61')"
    )
    op.execute(
        "CREATE TRIGGER posts_ai AFTER INSERT ON posts BEGIN "
        "INSERT INTO posts_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END"
    )
    op.execute(
        "CREATE TRIGGER posts_ad AFTER DELETE ON posts BEGIN "
        "INSERT INTO posts_fts(posts_fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body); END"
    )
    op.execute(
        "CREATE TRIGGER posts_au AFTER UPDATE OF title, body ON posts BEGIN "
        "INSERT INTO posts_fts(posts_fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body); "
        "INSERT INTO posts_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END"
    )


def downgrade() -> None:
    for t in ("knowledge_chunks_ai", "knowledge_chunks_ad", "knowledge_chunks_au", "posts_ai", "posts_ad", "posts_au"):
        op.execute(f"DROP TRIGGER IF EXISTS {t}")
    op.execute("DROP TABLE IF EXISTS knowledge_fts")
    op.execute("DROP TABLE IF EXISTS posts_fts")
