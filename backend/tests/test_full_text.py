from app.services.full_text import FullTextFetcher


def test_extract_main_content():
    fetcher = FullTextFetcher()
    html = """
    <html><body>
        <article><p>Main content here.</p></article>
        <aside>Sidebar</aside>
    </body></html>
    """
    content = fetcher._extract_content(html)
    assert "Main content" in content
    assert "Sidebar" not in content


def test_extract_strips_nav_script():
    fetcher = FullTextFetcher()
    html = """
    <html><body>
        <nav>Menu items</nav>
        <script>var x = 1;</script>
        <p>Real content here.</p>
        <footer>Footer text</footer>
    </body></html>
    """
    content = fetcher._extract_content(html)
    assert "Real content" in content
    assert "Menu items" not in content
    assert "var x" not in content
