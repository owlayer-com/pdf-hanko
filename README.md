# PDF Hanko

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

日本のハンコ文化に特化した、macOS 向けの PDF 電子署名アプリケーションです。

あらかじめ登録した印影画像と電子証明書（PKCS#12 形式のファイル、または
マイナンバーカードの公的個人認証サービス / JPKI）を使い、PDF 上での
「押印」操作によって、見た目のハンコと PAdES 準拠の電子署名を同時に付与します。

## 簡易デモ : Quick Demo
<video src="https://github.com/user-attachments/assets/13377871-00cf-4624-970a-bc46b81bed69" controls></video>

## 免責事項 : Disclaimer

> ⚠️ **本ソフトウェアは MIT ライセンスで「無保証 (AS IS)」で提供されます。**
> 「PAdES 準拠」は本アプリが生成する PDF 電子署名の技術仕様上の形式を示すものであり、
> 署名の法的有効性、本人性、証明書の信頼性、適格電子署名としての要件充足を保証する
> ものではありません。これらは、使用する証明書・運用方法・受領者側の
> 検証環境・適用される法令や契約条件などに依存します。重要な契約・法的書類に使用する
> 場合は、事前に十分な検証を行ってください。詳細は [LICENSE](LICENSE) を参照してください。

## 開発の背景 : Background

> 📝 開発の背景や使い方を [note の紹介記事](https://note.com/owlayer/n/n1f15473c066e) にまとめました。
> 本アプリを気に入っていただけた場合、記事の有料パート購入で開発の継続をご支援いただけると嬉しいです。

## 主な機能 : Features

- **ハンコ登録**: 印影画像、電子証明書、名前、サイズを登録・編集・削除
- **電子証明書の選択**: 証明書として **PKCS#12 ファイル** と
  **マイナンバーカード**（公的個人認証 / JPKI の署名用電子証明書）の両方に対応。
  マイナンバーカードを使う場合、秘密鍵はカードから取り出されず、カード内で署名値が生成されます
- **PDF への押印**: PDF を表示し、ドラッグで押印位置を指定して、1 クリックで見た目のハンコと PAdES 電子署名を同時に付与
- **複数押印 / 再署名**: すでに署名済みの PDF にも追加で押印可能（甲乙押印、複数ページ押印に対応）
- **pyHanko CLI 連携**: 「表示」メニューから、確定した押印位置を pyHanko CLI の `--field` 引数形式で表示・コピーできます（CLI でのバッチ署名に流用可）
- **完全ローカル動作**: ネットワーク通信なし。PDF・印影・証明書・パスワードは
  すべて Mac 内のみで処理（マイナンバーカードを使う場合、秘密鍵はカード内に留まり、
  証明書本体は Mac に永続保存されません）

## プライバシー : Privacy

本アプリはいかなるネットワーク通信も行いません。すべてのデータ（PDF・印影画像・
証明書・パスワード）は利用者の Mac 内のみで処理され、外部に送信されることは
ありません。設定ファイルは `~/Library/Application Support/PdfHanko/` 配下に
保存されます。

PKCS#12 証明書のパスワードは永続化されず、署名処理中のみメモリに保持されます。

マイナンバーカード署名を使う場合、本アプリは macOS の PC/SC（スマートカード
サービス）経由で、接続された IC カードリーダーおよび挿入されたカードと通信します。
これはローカルのデバイス通信のみで、ネットワーク送信は行いません。署名用パスワードは
永続化されず、カードへの認証時のみメモリに保持されます。カードから読み出して保存する
のは署名用電子証明書のシリアル番号と氏名（Common Name）のみで、これらも Mac 内に
留まります。

## 動作環境 : Requirements

- macOS（Apple Silicon）
- Python 3.11+ （ソースから実行する場合。`uv` が該当バージョンを自動でセットアップします）

> ℹ️ Intel Mac は開発者の手元に検証環境がないため、動作未確認です。動作する可能性は
> ありますが、サポート対象外とさせてください。

### マイナンバーカード署名を使う場合 : For Using My Number Card Signing

マイナンバーカードでの署名には、以下が追加で必要です。

- マイナンバーカード（公的個人認証サービス対応。**署名用電子証明書**が有効なもの）
- 署名用パスワード（券面事項入力補助用や利用者証明用ではなく、6〜16 桁の英数字の方）
- PC/SC 対応の IC カードリーダー（接触型 / NFC 対応）
  - macOS の PC/SC（標準搭載）経由でカードと通信します。専用ドライバなしで
    認識されるリーダーが利用できます。

#### 検証済みカードリーダー : Verified Card Readers

| 製品 | 種別 | 備考 |
| --- | --- | --- |
| **ソニー RC-S300（PaSoRi）** | NFC（非接触） | 当方（Apple Silicon Mac）で署名まで動作確認済み |

> ℹ️ 上記以外の PC/SC 対応リーダーでも動作する可能性がありますが、当方で検証
> できているのは上表のリーダーのみです。
>
> ⚠️ **署名用パスワードを 5 回連続で間違えるとカードがロックされ、市区町村の窓口での
> 解除が必要になります。** 本アプリは送信前に残り試行回数を確認し、残回数が少ない場合は
> 警告します。

## ダウンロード : Download

[Releases 一覧](https://github.com/owlayer-com/pdf-hanko/releases) から最新版の
`PDF Hanko-X.Y.Z.dmg`（約 60 MB）をダウンロードできます。通常はページ最上部の
"Latest" と表示されているリリースが最新版です。

### インストール手順 : Installation Steps

1. ダウンロードした `.dmg` をダブルクリックして開く
2. 表示されるウィンドウで `PDF Hanko.app` を `Applications` フォルダにドラッグする
3. `.dmg` をアンマウント（取り出し）
4. `Applications` から `PDF Hanko.app` を起動

初回起動時は macOS Gatekeeper の警告が表示されます。下記の
「[macOS Gatekeeper の警告について](#releases-からダウンロードして使う場合-macos-gatekeeper-の警告について--macos-gatekeeper-warning-when-using-releases)」
を参照してください。

## 事前準備 : Prerequisites

「ソースから実行する」「`.app` バンドルを自分でビルドする」場合は、いずれも
パッケージマネージャの [uv](https://github.com/astral-sh/uv) が必要です。
uv は、本プロジェクトの依存関係の解決、仮想環境の管理、Python ランタイムのセットアップを
すべて担当します。

> ℹ️ リリース版の `.dmg` をダウンロードして使うだけなら uv は不要です。

### Homebrew でインストール（推奨） : Install via Homebrew (Recommended)

```bash
brew install uv
```

### 公式インストールスクリプトでインストール : Install via Official Script

Homebrew を使わない場合：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

詳細は [uv 公式ドキュメント](https://docs.astral.sh/uv/) を参照してください。
uv は Python ランタイム自体も管理するため、別途 Python をインストールする
必要はありません。

## インストール / 実行 : Install / Run

### ソースからの実行（推奨） : Run from Source (Recommended)

```bash
git clone https://github.com/owlayer-com/pdf-hanko.git
cd pdf-hanko
uv sync
uv run python -m pdfhanko
```

### `.app` バンドルを自分でビルド : Build the `.app` Bundle Yourself

[Briefcase](https://briefcase.readthedocs.io/) を利用します（`pyproject.toml`
に設定済み）。

```bash
uv run briefcase create macOS
uv run briefcase build macOS
uv run briefcase run macOS
# .app バンドルは build/pdfhanko/macos/app/ 配下に生成される
```

### Releases からダウンロードして使う場合: macOS Gatekeeper の警告について : macOS Gatekeeper Warning When Using Releases

GitHub Releases に添付されている `.dmg` には **Apple Developer ID 署名が
付与されていません**。そのため、`.dmg` を開いた後に展開された `PDF Hanko.app`
を初回起動するとき、macOS の Gatekeeper による警告（「開発元が未確認のため
開けません」など）が表示されます。

これは本アプリに限らず、署名されていない macOS アプリで発生する一般的な挙動です。
起動方法は以下の通りです：

#### システム設定から許可する : Allow via System Settings

1. `.dmg` を開き、`PDF Hanko.app` を `Applications` フォルダにドラッグしてインストールする
2. 通常どおり `PDF Hanko.app` をダブルクリックする → 警告が表示される（OK を押して閉じる）
3. **アップルメニュー → システム設定 → プライバシーとセキュリティ**
4. 画面を下までスクロールすると、「"PDF Hanko" は開発元を確認できないため使用が
   ブロックされました」という表示の右に「**このまま開く**」または「**開発元にかかわらず開く**」
   というボタンがあるのでクリックする
5. Touch ID または管理者パスワードで認証
6. 再度 `PDF Hanko.app` をダブルクリックすると起動できる

#### 自分でソースからビルドする : Build from Source Yourself

警告を回避する最もシンプルな方法は、自分でソースからビルドすることです。
上記「ソースからの実行」または「`.app` バンドルを自分でビルド」の手順に従って
ください。コードは公開されているため、内容を確認したうえで利用できます。

> ℹ️ 商用アプリのように毎回 Developer ID 署名と Apple の公証を行う運用は、本 OSS
> プロジェクトでは行っていません。これが気になる方は、ソースから自分で
> ビルドして利用することを推奨します。

## 使い方 : Usage

1. アプリを起動する
2. 「ハンコを登録...」から印影画像と証明書を登録する。証明書は登録ダイアログの
   「証明書種別」で **PKCS#12 ファイル** か **マイナンバーカード** を選べる
3. 「PDF を開く...」で署名対象の PDF を選ぶ
4. 右ペインのハンコをクリックして選択する
5. PDF 上で押印したい位置までマウスをドラッグする → 離した位置に押印プレビューが表示される
6. 「署名して保存...」をクリックする → 保存先・パスワードを入力する → 完了

### マイナンバーカードで署名する : Signing with My Number Card

1. カードリーダーを Mac に接続する
2. 「ハンコを登録...」で「証明書種別」に **マイナンバーカード** を選び、印影画像と
   名前・サイズを設定する
3. 「カードを確認...」を押す → カードを挿入し、**署名用パスワード** を入力する。
   署名用電子証明書を読み出してアクセス可能か確認し、証明書のシリアル番号と
   氏名（Common Name）を登録する
4. 通常どおり PDF を開いて押印位置を決め、「署名して保存...」をクリックする
5. カードを挿入した状態で、ダイアログに再度 **署名用パスワード** を入力する
6. 署名処理はカード内で実行され、PAdES 署名付きの PDF が保存される

> ℹ️ 登録時に保存したカードのシリアル番号と、署名時に挿入されたカードのシリアル番号が
> 一致しない場合は、別のカードと判断して署名を中止します。

## pyHanko CLI で同じ押印位置を再現する : Reproduce the Same Stamp Position with pyHanko CLI

GUI で決めた押印位置を pyHanko CLI に渡せば、同じ場所に署名するバッチ処理が
組めます。

1. メニューバーの「表示」 →「pyHanko --field 表示」を ON にする
2. PDF 上で押印位置を決めると、ビューア下部に CLI 引数が表示される
   （例: `--field "1/470,630,530,690/[sign-name]"`）
3. テキストを選択してコピーし、`[sign-name]` 部分は任意の署名フィールド名に
   置換して pyHanko CLI に渡す

`--field` の書式は `PAGE/X1,Y1,X2,Y2/NAME` です。`[sign-name]` は **PDF 内部で
署名フィールドを識別するための名前** で、同一 PDF 内で重複しなければ任意の
文字列を指定できます（例: `Sign1`、`Signature1`、`CompanySeal` など）。
既に署名済みの PDF に追加で署名する場合は、既存フィールド名と衝突しない名前を
選んでください。

### 注意 : 本アプリと同じ大きさで押印する : Note: Stamp at the Same Size as This App

pyHanko の既定スタンプスタイルは、矩形の四辺に 5 pt のマージンと
不透明度 60%（= 40% 透過）の背景を入れるため、本アプリの出力よりも
一回り小さく・薄く仕上がります。本アプリと同じ大きさ・濃度で押印するには、
`pyhanko.yml` の `stamp-styles` で **背景マージンを 0 に、不透明度を 1 に**
上書きしてください。

```yaml
stamp-styles:
    mystyle:
        stamp-text: ""
        background: hanko.png
        background-opacity: 1
        border-width: 0
        background-layout:
            margins: {left: 0, right: 0, top: 0, bottom: 0}
```

CLI 実行時はこのスタイルを `--style-name mystyle` で参照します。`hanko.png`
には本アプリで登録したものと同じ印影画像（72 DPI 推奨）を指定してください。

### コマンド例 : Command Example

`pyhanko.yml`（上のサンプル）と PDF・印影画像・PKCS#12 証明書を同じディレクトリに
置いた状態で、本アプリと同等の見た目で署名するコマンド例：

```bash
pyhanko --config pyhanko.yml sign addsig \
    --field "1/470,630,530,690/Sign1" \
    --style-name mystyle \
    --use-pades \
    pkcs12 input.pdf output.pdf cert.p12
```

- `--config pyhanko.yml`: スタンプスタイル定義を読み込む。設定ファイル名を
  `pyhanko.yml`（pyhanko のデフォルト名）にし、カレントディレクトリに置けば
  本オプションは省略可能
- `--field "..."`: 本アプリのステータス行からコピーした文字列を貼り付け、
  末尾の `[sign-name]` を任意のフィールド名（ここでは `Sign1`）に置換
- `--style-name mystyle`: `pyhanko.yml` で定義したスタイル名を参照
- `--use-pades`: 本アプリと同じく PAdES 準拠で署名する
- `pkcs12 input.pdf output.pdf cert.p12`: PKCS#12 証明書で `input.pdf` を読み、
  `cert.p12` で署名し `output.pdf` を出力する

PKCS#12 のパスフレーズは標準入力か `--passfile` で渡します（詳細は
`pyhanko sign addsig pkcs12 --help`）。

## 開発 : Development

- GUI フレームワーク: [Toga / BeeWare](https://beeware.org/)
- PDF レンダリング: [pypdfium2](https://github.com/pypdfium2-team/pypdfium2)
- 電子署名: [pyHanko](https://github.com/MatthiasValvekens/pyHanko)
- IC カード通信 (PC/SC): [pyscard](https://github.com/LudovicRousseau/pyscard)
- パッケージング: [Briefcase](https://briefcase.readthedocs.io/)

### ディレクトリ構成 : Directory Structure

```
src/pdfhanko/
├── app.py              # toga.App 本体
├── coords.py           # 座標系変換ユーティリティ
├── jpki.py             # マイナンバーカード (JPKI) APDU 通信ラッパ
├── rendering.py        # pypdfium2 ラッパ
├── signing.py          # pyHanko ラッパ (PKCS#12 / JPKI Signer)
├── storage.py          # ハンコ永続化
├── logging_config.py   # ログ出力設定
├── resources/
│   ├── pdfhanko.png    # アイコン元画像 (1024×1024)
│   └── pdfhanko.icns   # macOS 用アイコン (build_icns.py で生成)
└── windows/
    ├── main_window.py      # メインウィンドウ
    ├── pdf_view.py         # PDF 表示・押印 UI
    ├── register_window.py  # ハンコ登録/編集ダイアログ
    ├── pin_dialog.py       # 署名用パスワード入力モーダル (JPKI)
    └── password_dialog.py  # パスワード入力モーダル (PKCS#12)

scripts/
├── generate_placeholder_icon.py  # 仮アイコン (朱色の丸印) の PNG を生成
└── build_icns.py                 # PNG から .icns を生成
```

### アイコンの更新 : Updating the Icon

アプリアイコンは `src/pdfhanko/resources/pdfhanko.png` を元画像として、
専用スクリプトで macOS 用 `.icns` に変換する仕組みです。

```bash
# 1. デザインした PNG (1024×1024, RGBA 推奨) を以下のパスに配置
#    src/pdfhanko/resources/pdfhanko.png

# 2. PNG → .icns に変換 (16/32/64/128/256/512/1024 px をマルチサイズ同梱)
uv run python scripts/build_icns.py

# 3. .app バンドルに反映 (--update-resources がポイント)
uv run briefcase update macOS --update-resources
uv run briefcase build macOS
```

`build_icns.py` は入力 PNG をフルブリード（1024×1024 の全面デザイン）とみなし、
macOS Big Sur 以降のガイドラインに合わせて **約 82% に縮小・中央配置**します。
これにより Dock や Launchpad で他の macOS アプリと並んだときに自然なサイズに
なります。サイズ感を調整したい場合は
[scripts/build_icns.py](scripts/build_icns.py) の `MACOS_SAFE_AREA_RATIO`
（デフォルト `0.824`）を 0.80〜0.95 の範囲で変更してください。

仮アイコン（朱色の丸印 + 「印」）を再生成したい場合は次を実行します：

```bash
uv run python scripts/generate_placeholder_icon.py
```

### リリースビルドの作成（メンテナ向け） : Creating a Release Build (For Maintainers)

GitHub Releases に添付する `.dmg` を作成する手順：

```bash
# 1. (必要なら) pyproject.toml の version を更新
#    [project] section の version = "X.Y.Z" を新バージョンに書き換える

# 2. Briefcase でビルド + パッケージング (ad-hoc 署名)
#    アイコン (src/pdfhanko/resources/pdfhanko.icns) を更新した場合は
#    --update-resources を併用する
uv run briefcase update macOS --update-resources   # ソース + アイコンを反映
uv run briefcase build macOS                       # .app バンドルをビルド
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

`.dmg` には Apple Developer ID 署名を付与していません。利用者は
[「macOS Gatekeeper の警告について」](#releases-からダウンロードして使う場合-macos-gatekeeper-の警告について--macos-gatekeeper-warning-when-using-releases)
の手順で起動する必要があります。リリースノートに同様の案内を含めると親切です。

## ライセンス : License

[MIT License](LICENSE) — Copyright (c) 2026 owlayer-com

依存しているオープンソースコンポーネントのライセンス表示は [NOTICE.md](NOTICE.md)
にまとめています。
アプリまたは `.dmg` を再配布する場合は、`LICENSE` と `NOTICE.md` を同梱してください。

## 貢献 : Contributing

バグ報告・改善提案は GitHub の Issues / Pull Requests からお願いします。
