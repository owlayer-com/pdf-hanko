# PDF Hanko

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

日本のハンコ文化に特化した、macOS 向け PDF 電子署名アプリケーション。

あらかじめ登録した印影画像と PKCS#12 形式の証明書を用いて、PDF 上に
「押印」操作で見た目のハンコと PAdES 準拠の電子署名を同時に付与します。

> ⚠️ **本ソフトウェアは MIT ライセンスで「無保証 (AS IS)」で提供されます。**
> 電子署名の法的有効性は、使用する証明書・運用方法・受領者側の検証環境などに
> 依存します。重要な契約・法的書類に使用する場合は、事前に十分な検証を行って
> ください。詳細は [LICENSE](LICENSE) を参照してください。

## 主な機能

- **ハンコ登録**: 印影画像 + PKCS#12 証明書 + 名前・サイズを登録・編集・削除
- **PDF 押印**: PDF を表示 → ドラッグで押印位置を指定 → 1 クリックで視覚ハンコ + PAdES 電子署名を同時付与
- **複数押印 / 再署名**: 既に署名済みの PDF にもさらに押印可能（甲乙押印、割印、複数ページ押印に対応）
- **完全ローカル動作**: ネット通信なし。PDF・印影・証明書・パスワードはすべて Mac 内のみで処理

## プライバシー

本アプリはいかなるネットワーク通信も行いません。すべてのデータ（PDF・印影画像・
証明書・パスワード）は使用者の Mac 内のみで処理され、外部に送信されることは
ありません。設定ファイルは `~/Library/Application Support/PdfHanko/` 配下に
保存されます。

PKCS#12 証明書のパスワードは永続化されず、署名処理中のみメモリに保持されます。

## 動作環境

- macOS（Apple Silicon / Intel）
- Python 3.11+

## インストール / 実行

### ソースからの実行（推奨）

[uv](https://github.com/astral-sh/uv) をインストールしておいてください。

```bash
git clone https://github.com/owlayer-com/pdf-hanko.git
cd pdf-hanko
uv sync
uv run python -m pdfhanko
```

### `.app` バンドルを自分でビルド

[Briefcase](https://briefcase.readthedocs.io/) を利用します（`pyproject.toml`
に設定済み）。

```bash
uv run briefcase create macOS
uv run briefcase build macOS
uv run briefcase run macOS
# .app バンドルは build/pdfhanko/macos/app/ 配下に生成される
```

### Release からダウンロードして使う場合: macOS Gatekeeper の警告について

GitHub Releases に添付されている `.app` / `.dmg` には **Apple Developer ID
署名が付いていません**。そのため、初回起動時に macOS の Gatekeeper による警告
（「開発元が未確認のため開けません」など）が表示されます。

これは本アプリに限らず、署名されていない macOS アプリで発生する一般的な挙動です。
回避方法は以下の通りです：

#### 方法 1: 右クリックから開く（macOS Sonoma 14 以前で確実）

1. Finder で `PDF Hanko.app` を探す
2. **右クリック（または control + クリック）** → メニューから「**開く**」を選択
3. 警告ダイアログで「**開く**」をクリック

一度この手順を実行すれば、以降は通常通り Dock / Launchpad からダブルクリックで
起動できます。

#### 方法 2: システム設定から許可（macOS Sequoia 15 以降で必要なことが多い）

新しい macOS では方法 1 が制限されているため、システム設定からの許可が必要です：

1. 通常通り `PDF Hanko.app` をダブルクリックする → 警告が表示される（OK を押して閉じる）
2. **アップルメニュー → システム設定 → プライバシーとセキュリティ**
3. 画面を下までスクロールすると、「"PDF Hanko" は開発元を確認できないため使用が
   ブロックされました」という表示の右に「**このまま開く**」または「**開発元にかかわらず開く**」
   というボタンがあるのでクリック
4. Touch ID または管理者パスワードで認証
5. 再度 `PDF Hanko.app` をダブルクリックすると起動できる

#### 方法 3: 自分でソースからビルドする（最も安全）

警告を回避する最もシンプルな方法は、自分でソースからビルドすることです。
上記「ソースからの実行」または「`.app` バンドルを自分でビルド」の手順に従って
ください。コードは公開されているので、安心して使えます。

> ℹ️ 商用のように毎回 Developer ID 署名と Apple の公証を行う運用は、本 OSS
> プロジェクトでは行っていません。これが気になる方は、ソースから自分で
> ビルドして利用することを推奨します。

## 使い方

1. アプリを起動する
2. 「ハンコを登録...」から印影画像と PKCS#12 証明書を登録する
3. 「PDF を開く...」で署名対象の PDF を選ぶ
4. 右ペインのハンコをクリックして選択する
5. PDF 上で押印したい位置にマウスをドラッグ → 離した位置に押印プレビューが出る
6. 「署名して保存...」をクリック → 保存先・パスワード入力 → 完了

## 開発

- GUI フレームワーク: [Toga / BeeWare](https://beeware.org/)
- PDF レンダリング: [pypdfium2](https://github.com/pypdfium2-team/pypdfium2)
- 電子署名: [PyHanko](https://github.com/MatthiasValvekens/pyHanko)
- パッケージング: [Briefcase](https://briefcase.readthedocs.io/)

### ディレクトリ構成

```
src/pdfhanko/
├── app.py              # toga.App 本体
├── coords.py           # 座標系変換ユーティリティ
├── rendering.py        # pypdfium2 ラッパ
├── signing.py          # PyHanko ラッパ
├── storage.py          # ハンコ永続化
└── windows/
    ├── main_window.py      # メインウィンドウ
    ├── pdf_view.py         # PDF 表示・押印 UI
    ├── register_window.py  # ハンコ登録/編集ダイアログ
    └── password_dialog.py  # パスワード入力モーダル
```

### リリースビルドの作成（メンテナ向け）

GitHub Releases に添付する `.dmg` を作成する手順：

```bash
# 1. (必要なら) pyproject.toml の version を更新
#    [project] section の version = "X.Y.Z" を新バージョンに書き換える

# 2. Briefcase でビルド + パッケージング (ad-hoc 署名)
uv run briefcase update macOS      # 直近のソース変更を反映
uv run briefcase build macOS       # .app バンドルをビルド
uv run briefcase package macOS --adhoc-sign

# 出力: dist/PDF Hanko-X.Y.Z.dmg (約 60 MB)

# 3. git タグ + GitHub Release を作成して .dmg を添付
git tag vX.Y.Z
git push origin vX.Y.Z
gh release create vX.Y.Z \
    --title "vX.Y.Z" \
    --notes "リリースノート本文..." \
    "dist/PDF Hanko-X.Y.Z.dmg"
```

`.dmg` には Apple Developer ID 署名は付与していません。利用者は
[「macOS Gatekeeper の警告について」](#release-からダウンロードして使う場合-macos-gatekeeper-の警告について)
の手順で起動する必要があります。リリースノートに同様の案内を含めると親切です。

## ライセンス

[MIT License](LICENSE) — Copyright (c) 2026 owlayer-com

依存しているオープンソースコンポーネントのライセンス表示は [NOTICE.md](NOTICE.md)
にまとめています。

## 貢献

バグ報告・改善提案は GitHub の Issues / Pull Requests からお願いします。
