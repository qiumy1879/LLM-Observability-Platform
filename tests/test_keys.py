"""API Key 管理接口测试"""

import pytest


@pytest.mark.asyncio
async def test_create_key(client):
    """创建 API Key"""
    # 先做一次简单请求确保 DB 连接就绪（aiosqlite 连接初始化有时延）
    await client.get("/health")
    resp = await client.post("/api/keys", json={"name": "test-key", "rate_limit": 60})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-key"
    assert data["key"].startswith("sk-")
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_list_keys_empty(client):
    """空列表"""
    resp = await client.get("/api/keys")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_keys(client):
    """创建后列出"""
    await client.post("/api/keys", json={"name": "key-a"})
    await client.post("/api/keys", json={"name": "key-b"})
    resp = await client.get("/api/keys")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


@pytest.mark.asyncio
async def test_disable_key(client):
    """禁用 Key"""
    resp = await client.post("/api/keys", json={"name": "to-disable"})
    key_id = resp.json()["id"]

    resp2 = await client.patch(f"/api/keys/{key_id}", params={"is_active": False})
    assert resp2.status_code == 200
    assert resp2.json()["is_active"] is False


@pytest.mark.asyncio
async def test_delete_key(client):
    """删除 Key"""
    resp = await client.post("/api/keys", json={"name": "to-delete"})
    key_id = resp.json()["id"]

    resp2 = await client.delete(f"/api/keys/{key_id}")
    assert resp2.status_code == 204
