from fastapi.testclient import TestClient


def test_public_pages_accessible_when_logged_out(client: TestClient):
    for path in ["/about", "/pricing", "/changelog", "/robots.txt", "/sitemap.xml"]:
        response = client.get(path)
        assert response.status_code == 200, f"Expected 200 for {path}, got {response.status_code}"

    # Content assertions
    about_res = client.get("/about")
    assert "kalibrasi" in about_res.text

    pricing_res = client.get("/pricing")
    assert "Gratis" in pricing_res.text

    changelog_res = client.get("/changelog")
    assert "3 Oktober 2026" in changelog_res.text

    robots_res = client.get("/robots.txt")
    assert "Sitemap: https://raschlab.idzharulhuda.com/sitemap.xml" in robots_res.text
    assert robots_res.headers.get("content-type", "").startswith("text/plain")

    sitemap_res = client.get("/sitemap.xml")
    assert sitemap_res.headers.get("content-type", "").startswith("application/xml")
    assert "https://raschlab.idzharulhuda.com/" in sitemap_res.text
    assert "https://raschlab.idzharulhuda.com/about" in sitemap_res.text
    assert "https://raschlab.idzharulhuda.com/pricing" in sitemap_res.text
    assert "https://raschlab.idzharulhuda.com/changelog" in sitemap_res.text
