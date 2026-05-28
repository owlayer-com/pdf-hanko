# Changelog

このプロジェクトの主な変更点をリリース単位で記録しています。
フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に準拠し、
バージョニングは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

(次の変更点はここに追記します。)

## [0.3.0] - 2026-05-28

マイナンバーカード（公的個人認証 / JPKI）による署名に対応したリリース。
PKCS#12 ファイルに加えて、署名用秘密鍵をカード内に保持したまま署名できる
ようになった。

### Added

- マイナンバーカードの署名用電子証明書による PAdES 署名に対応
  ([src/pdfhanko/jpki.py](src/pdfhanko/jpki.py),
  [src/pdfhanko/signing.py](src/pdfhanko/signing.py))。
  pyscard 経由で PC/SC でカードと通信し、COMPUTE DIGITAL SIGNATURE APDU で
  RSA PKCS#1 v1.5 署名を行う。署名用秘密鍵はカードから取り出されない。
- ハンコ登録/編集ダイアログに「証明書種別」（PKCS#12 ファイル / マイナンバー
  カード）の選択を追加 ([src/pdfhanko/windows/register_window.py](src/pdfhanko/windows/register_window.py))。
  「カードを確認...」で署名用パスワードを入力して署名用電子証明書を読み出し、
  シリアル番号と氏名 (Common Name) を登録する。
- 署名用パスワード入力モーダルを追加
  ([src/pdfhanko/windows/pin_dialog.py](src/pdfhanko/windows/pin_dialog.py))。
- 署名用パスワードの**残り試行回数を送信前に確認**し、残回数が少ない場合に
  警告する仕組みを追加（5 回連続失敗によるカードロックの予防）。
  登録時のカードと署名時のカードのシリアル番号を照合し、不一致時は署名を中止する
  ([src/pdfhanko/signing.py](src/pdfhanko/signing.py),
  [src/pdfhanko/windows/main_window.py](src/pdfhanko/windows/main_window.py))。

### Changed

- ハンコ永続化スキーマ (`Hanko`) に `cert_type` / `jpki_cert_serial` /
  `jpki_cert_subject_cn` フィールドを追加
  ([src/pdfhanko/storage.py](src/pdfhanko/storage.py))。既知フィールドのみを
  読み込む方式に変更し、旧バージョンで作成した設定ファイルからの読み込みには
  後方互換。
- ハンコ一覧で証明書種別をアイコン表示（📄 PKCS#12 / 💳 マイナンバーカード）
  ([src/pdfhanko/windows/main_window.py](src/pdfhanko/windows/main_window.py))。
- README に動作環境（検証済みカードリーダー: ソニー RC-S300 / PaSoRi）、
  マイナンバーカードでの署名手順を追記。

### Dependencies

- `pyscard>=2.0.10` を追加（PC/SC 経由の IC カード通信）。

### Notes

- ⚠️ **本バージョンでハンコの登録・編集・削除を行うと、設定ファイル
  (`~/Library/Application Support/PdfHanko/`) に v0.3.0 で追加した新フィールドが
  書き込まれ、v0.2 以前にはダウングレードできなくなります。** v0.2 以前は未知
  フィールドの読み込みに対応していないため、起動時にハンコ一覧の読み込みで
  エラーになります。ダウングレードが必要な場合は事前に設定ファイルを
  バックアップしてください。

## [0.2.0] - 2026-05-26

PDF Hanko 単体での pyHanko CLI 連携支援、File メニュー充実、未保存時の
誤終了防止を中心とした機能強化リリース。

### Added

- pyHanko CLI 用 `--field` 引数文字列を PDF ビュー下部に表示する機能を追加
  ([src/pdfhanko/windows/pdf_view.py](src/pdfhanko/windows/pdf_view.py))。
  「表示」メニューからオン/オフを切り替えでき、設定は
  `~/Library/Application Support/PdfHanko/settings.json` に永続化される
  ([src/pdfhanko/settings.py](src/pdfhanko/settings.py))。
  GUI で押印位置を確定したあと、pyHanko CLI / `pyhanko --style-name` で
  バッチ署名する際の座標貼り付け作業を不要にする。
- 「File」メニューに「PDF を開く...」(Cmd+O) と「PDF に署名して保存...」
  (Cmd+S) のコマンドを追加 ([src/pdfhanko/app.py](src/pdfhanko/app.py))。
  ツールバーボタンとショートカットの両方から同じ操作を実行できる。
- ウィンドウクローズ要求 (左上の赤ボタン / File > Close / Cmd+W) および
  アプリ終了要求 (Cmd+Q) に対する未保存確認ダイアログを追加
  ([src/pdfhanko/windows/main_window.py](src/pdfhanko/windows/main_window.py),
  [src/pdfhanko/app.py](src/pdfhanko/app.py))。
  押印位置を確定したまま保存せず終了しようとすると確認ダイアログが出る。

### Changed

- README に macOS スクリーンショット
  ([docs/screenshots/main_window.png](docs/screenshots/main_window.png))、
  Releases 一覧へのリンク、PAdES 表記の注意書き、`pyhanko --style-name`
  との併用フローを追記し、配布・運用周りの情報を整理。
- NOTICE.md の第三者ライセンス記載を更新。

## [0.1.2] - 2026-05-23

v0.1.1 リリース後に確認された終了時クラッシュの修正。

### Fixed

- アプリ終了時に `EXC_BAD_ACCESS (SIGSEGV)` でクラッシュする問題を修正。
  Toga / rubicon-objc と Cocoa の autorelease pool 終了タイミングの競合により、
  Python finalize 後に pool 内オブジェクトの dealloc が死んだ
  `PyInterpreterState` を参照していた。`main_loop()` 終了直後に
  `logging.shutdown()` + `os._exit()` で即時終了する形に変更
  ([src/pdfhanko/__main__.py](src/pdfhanko/__main__.py))。
  HankoStore は変更時に都度永続化しているため通常 shutdown を経由
  しなくてもデータ整合性に影響はない。

## [0.1.1] - 2026-05-22

v0.1.0 リリース後に確認されたバグの修正と、UI の小幅な改善。

### Fixed

- 押印・署名後の PDF で印影が署名矩形より一回り小さく描画される問題を
  修正 (PyHanko `BaseStampStyle.background_layout` の既定 5 pt
  uniform margin を 0 で上書き)。24 mm 角の矩形が約 20 mm 角に縮んで
  いた現象が解消されます。

### Changed

- ツールバーの配置を変更 — 「PDF を開く」「押印」を左寄せ、「ハンコを
  登録...」を右寄せに分離し、操作頻度に合わせた導線へ整理。
- ハンコ一覧の選択中の行を再度クリックすると選択を解除できるように
  挙動を変更 (PDF 側のドラッグ操作も無効化)。
- ハンコ未登録時の案内文、変更/削除ボタン幅・余白を微調整。
- README を全体校正 — 語句の統一と自然な日本語表現への修正。

## [0.1.0] - 2026-05-22

初回リリース。日本のハンコ文化に特化した macOS 向け PDF 電子署名アプリ。

### Added

#### コア機能
- ハンコ登録・編集・削除（印影画像 + PKCS#12 証明書 + 名前・サイズ・メモ）
- PDF 表示（pypdfium2、ページ送り、72 DPI 正規化）
- ドラッグでの押印位置指定 + 半透明プレビュー
- PAdES 準拠の電子署名（PyHanko、async API）
- 複数押印 / 既存署名済み PDF への追加押印（incremental update でユニーク
  フィールド名を生成し、甲乙押印・割印・複数ページ押印に対応）
- ハイブリッド xref を含む PDF への対応 (`strict=False`)
- 完全ローカル動作（ネット通信なし、データは Mac 内のみで処理）

#### UI / UX
- 「PDF Hanko について」(About) ダイアログ — バージョン・ライセンス・OSS 帰属を表示
- 「ヘルプ」メニュー — GitHub README を既定ブラウザで開く
- 朱色の丸印 + PDF 書類モチーフのアプリアイコン
- macOS Big Sur 以降のアイコン安全領域 (約 82%) に自動適応

#### 配布 / 運用
- macOS 向け `.app` バンドル + `.dmg` パッケージング (Briefcase, ad-hoc 署名)
- ユニバーサルビルド (Apple Silicon / Intel 両対応)
- 終了時のリソース明示解放 (segfault 抑制)
- エラーログ出力 — `~/Library/Logs/PdfHanko/pdfhanko.log` (WARNING 以上、
  ローテーション付き、未捕捉例外も記録)
- `pdfhanko.__version__` を `pyproject.toml` と同期 (`importlib.metadata`)

### Notes

- 本リリースは **MIT ライセンスで「無保証 (AS IS)」で提供**されます。
- `.dmg` には Apple Developer ID 署名は付与されていません。初回起動時に
  macOS Gatekeeper の警告が出ますので、README の解除手順を参照してください。
- 電子署名の法的有効性は使用する証明書・運用方法に依存します。重要な
  契約・法的書類で利用する場合は事前検証を強く推奨します。

[Unreleased]: https://github.com/owlayer-com/pdf-hanko/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/owlayer-com/pdf-hanko/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/owlayer-com/pdf-hanko/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/owlayer-com/pdf-hanko/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/owlayer-com/pdf-hanko/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/owlayer-com/pdf-hanko/releases/tag/v0.1.0
