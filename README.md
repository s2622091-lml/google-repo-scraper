# Google の GitHub リポジトリ一覧

GitHub の Google 組織が公開しているリポジトリを全件取得し、リポジトリ名、主要な言語、スター数を SQLite に保存するプログラムです。

## 実行方法

Python 3.9 以上で実行できます。追加ライブラリのインストールは不要です。

```bash
python3 scraper.py
```

処理中はページ数と累計件数が表示されます。取得が完了すると、同じフォルダに `google_repositories.db` が作られ、全件がスター数の多い順に表示されます。保存済みのデータは次のコマンドで再表示できます。

```bash
python3 scraper.py --show-only
```

GitHub のアクセス制限などで取得が途中で止まった場合は、時間を置いて `python3 scraper.py` を再実行します。保存したページの次から再開します。最初から取得し直す場合は `python3 scraper.py --restart` を実行します。

## 取得・保存の仕組み

1. [Google のリポジトリ一覧](https://github.com/orgs/google/repositories)を名前順で開き、GitHub が返す HTML から一覧のデータを取り出します。GitHub API は使用しません。
2. HTML に含まれるページ数を使って最終ページまで読み込みます。リクエストのたびに `time.sleep(1)` で1秒待ちます。
3. 取得中の重複や件数の変化を確認し、GitHub が示す件数と一致したデータを SQLite に保存します。主要な言語が表示されない場合は `NULL` を保存します。
4. 次の `SELECT` 文で取得結果を表示します。

```sql
SELECT name, primary_language, stars
FROM repositories
ORDER BY stars DESC, name ASC;
```
