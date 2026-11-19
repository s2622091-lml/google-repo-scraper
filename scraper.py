"""Google の公開リポジトリを収集して SQLite に保存する。"""

import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPOSITORIES_URL = "https://github.com/orgs/google/repositories"
DATABASE = Path(__file__).resolve().with_name("google_repositories.db")
CHECKPOINT = DATABASE.with_name("scrape-progress.json")


class EmbeddedDataParser(HTMLParser):
    """HTML に埋め込まれたリポジトリ一覧のデータを取り出す。"""

    def __init__(self):
        super().__init__()
        self.in_script = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.in_script = dict(attrs).get("data-target") == "react-app.embeddedData"

    def handle_data(self, data):
        if self.in_script:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False


def read_page(page_number):
    # 更新時刻で並べると、取得中の更新で行の順番が変わりやすい。
    query = urlencode({"q": "sort:name-asc", "page": page_number})
    request = Request(
        f"{REPOSITORIES_URL}?{query}",
        headers={"User-Agent": "University course project", "Accept": "text/html"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8")
    except HTTPError as error:
        if error.code == 429 or (error.code == 403 and error.headers.get("Retry-After")):
            raise ValueError(
                "GitHub のアクセス制限に達しました。時間を置いて再実行すると続きから再開します。"
            ) from error
        raise
    finally:
        time.sleep(1)

    parser = EmbeddedDataParser()
    parser.feed(html)
    data = json.loads("".join(parser.parts))["payload"]["orgReposPageRoute"]
    if data.get("errorMessage"):
        raise ValueError(data["errorMessage"])
    rows = []
    for repo in data["repositories"]:
        language = repo["primaryLanguage"]
        rows.append((repo["owner"], repo["name"], language["name"] if language else None, repo["starsCount"]))
    return {"pages": data["pageCount"], "total": data["repositoryCount"], "rows": rows}


def save_progress(pages):
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=CHECKPOINT.parent, delete=False) as output:
        temporary_path = Path(output.name)
        json.dump(pages, output, ensure_ascii=False)
    temporary_path.replace(CHECKPOINT)


def collect_repositories(restart=False):
    pages = []
    if not restart and CHECKPOINT.is_file():
        pages = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    cached_count = len(pages)
    first_page = pages[0] if pages else read_page(1)
    page_count = first_page["pages"]
    expected_count = first_page["total"]
    repositories = {}

    if page_count < 1 or expected_count < 1 or cached_count > page_count:
        raise ValueError("公開リポジトリの一覧が空です。")

    for page_number in range(1, page_count + 1):
        if page_number <= cached_count:
            page = pages[page_number - 1]
        else:
            page = first_page if page_number == 1 else read_page(page_number)
        if page["pages"] != page_count or page["total"] != expected_count:
            raise ValueError("取得中に件数が変わりました。--restart を付けてやり直してください。")

        for owner, name, language, stars in page["rows"]:
            if owner != "google" or not name or type(stars) is not int or stars < 0:
                raise ValueError(f"{page_number} ページ目のデータを確認してください。")
            if name in repositories:
                raise ValueError(f"{name} が重複しました。--restart を付けてやり直してください。")

            repositories[name] = (language, stars)

        if page_number > cached_count:
            pages.append(page)
            save_progress(pages)
        print(f"{page_number}/{page_count} ページ取得（累計 {len(repositories)} 件）", file=sys.stderr)

    if len(repositories) != expected_count:
        raise ValueError(f"表示件数 {expected_count} 件と一致しません。--restart を付けてやり直してください。")

    return repositories


def save_repositories(connection, repositories):
    # 全件の取得を確認したあとで、DB のデータをまとめて更新する。
    with connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS repositories (
                name TEXT PRIMARY KEY,
                primary_language TEXT,
                stars INTEGER NOT NULL CHECK (stars >= 0)
            )
        """)
        connection.execute("DELETE FROM repositories")
        connection.executemany(
            "INSERT INTO repositories (name, primary_language, stars) VALUES (?, ?, ?)",
            ((name, language, stars) for name, (language, stars) in repositories.items()),
        )


def show_repositories(connection):
    rows = connection.execute("""
        SELECT name, primary_language, stars
        FROM repositories
        ORDER BY stars DESC, name ASC
    """).fetchall()

    print(f"保存件数: {len(rows)}")
    print("リポジトリ名\t主要な言語\tスター数")
    for name, language, stars in rows:
        print(f"{name}\t{language or '未設定'}\t{stars}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--show-only", action="store_true", help="保存済みのデータを表示する")
    mode.add_argument("--restart", action="store_true", help="最初のページから取得し直す")
    args = parser.parse_args()

    try:
        if args.show_only:
            if not DATABASE.is_file():
                raise ValueError("先に python3 scraper.py を実行してください。")
            with closing(sqlite3.connect(DATABASE)) as connection:
                show_repositories(connection)
        else:
            repositories = collect_repositories(args.restart)
            with closing(sqlite3.connect(DATABASE)) as connection:
                save_repositories(connection, repositories)
                CHECKPOINT.unlink(missing_ok=True)
                show_repositories(connection)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
