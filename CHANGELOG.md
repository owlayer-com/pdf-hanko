# Changelog

このプロジェクトの主な変更点をリリース単位で記録しています。
フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に準拠し、
バージョニングは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

(次の変更点はここに追記します。)

## [0.3.1] - 2026-10-17

2026-10-16 のセキュリティレビューで挙がった指摘を修正したリリース。保存時の
原本の破損防止、秘密鍵などの権限の制限、設定ファイルの検証、PDF・画像の処理量の
上限、マイナンバーカードの PIN 検証の強化、配布物の依存の固定を行った。

### Security

- 保存先に入力 PDF と同じファイルを指定した場合に、署名処理の途中で入力が
  切り詰められて原本が壊れる問題を修正
  ([src/pdfhanko/signing.py](src/pdfhanko/signing.py),
  [src/pdfhanko/windows/main_window.py](src/pdfhanko/windows/main_window.py))。
  ハードリンク・シンボリックリンク経由の同一ファイルも検出し、署名用
  パスワードの入力前にエラーを表示して中止する。
- 署名済み PDF を同じディレクトリの一時ファイルに書き込み、成功時のみ
  保存先を置き換えるよう変更
  ([src/pdfhanko/fileutil.py](src/pdfhanko/fileutil.py))。署名に失敗しても
  不完全な PDF が残らず、既存の保存先ファイルも変更されない。
- アプリ専用データ（`~/Library/Application Support/PdfHanko/`）とログ
  （`~/Library/Logs/PdfHanko/`）の権限を、所有者のみアクセスできる設定
  （ディレクトリ `0700`、ファイル `0600`）に変更
  ([src/pdfhanko/fileutil.py](src/pdfhanko/fileutil.py),
  [src/pdfhanko/storage.py](src/pdfhanko/storage.py),
  [src/pdfhanko/settings.py](src/pdfhanko/settings.py),
  [src/pdfhanko/logging_config.py](src/pdfhanko/logging_config.py))。
  PKCS#12 の取り込みは内容だけを複製し、コピー元の権限・拡張属性
  （quarantine 等）を引き継がない。以前のバージョンで作成されたファイルは、
  起動時に自動で権限を修正する。
- ハンコ一覧（`hankos.json`）の内容を検証するよう変更
  ([src/pdfhanko/storage.py](src/pdfhanko/storage.py))。ID の形式・各項目の型・
  ファイルパスが想定と異なるエントリや、保存先がシンボリックリンクになっている
  エントリは読み込まない。印影画像と証明書の場所は、`hankos.json` に保存された
  パスではなく ID から組み立てるため、設定を書き換えてもアプリ専用フォルダの
  外にあるファイルの読み取り・上書き・削除には使えない。
- `hankos.json` が壊れている場合でも起動できるよう変更。問題があった場合は
  起動時にダイアログで知らせ、元のファイルは次の保存の前に
  `hankos.json.<日時>.bak` として退避する。
- ハンコ一覧（`hankos.json`）と設定（`settings.json`）、印影画像の保存を、
  一時ファイル経由の置き換えに変更し、書き込み途中の失敗でファイルが
  壊れないようにした。

- 巨大なページや高圧縮の PDF・画像によるメモリ枯渇・応答停止を防ぐため、
  処理量に上限を設けた ([src/pdfhanko/limits.py](src/pdfhanko/limits.py),
  [src/pdfhanko/rendering.py](src/pdfhanko/rendering.py))。PDF のファイル
  サイズ・ページ数・1 ページの描画サイズ、印影画像のファイルサイズ・ピクセル数を、
  メモリを確保する前に確認する。上限を超える PDF は開かずにエラーを表示し、
  上限を超えるページは「表示できません」と表示する。

- マイナンバーカードの署名用パスワード（PIN）の検証を強化
  ([src/pdfhanko/jpki.py](src/pdfhanko/jpki.py),
  [src/pdfhanko/windows/pin_dialog.py](src/pdfhanko/windows/pin_dialog.py))。
  途中に空白を含む PIN が入力チェックを通過し、そのままカードに送信されて
  残り試行回数を消費する問題を修正した。入力画面とカードへの送信直前の両方で、
  半角英数字のみ・6〜16 文字であることを確認し、合わない場合はカードに送信しない。
  空白は前後も含めて自動で取り除かず、エラーにする。
- 診断用コマンド `python -m pdfhanko.jpki` の `--pin` 引数を廃止
  ([src/pdfhanko/jpki.py](src/pdfhanko/jpki.py))。PIN がシェルの履歴や
  プロセスの引数に残らないよう、`--verify-pin` 指定時に対話入力させる。

- 配布用 `.app` に同梱するパッケージのバージョンを `uv.lock` に固定
  ([pyproject.toml](pyproject.toml), [constraints-macos.txt](constraints-macos.txt))。
  これまでは Briefcase の依存指定が `>=` で推移的な依存も固定していなかった
  ため、ビルド時点の最新版が入っていた（v0.3.0 の成果物では `idna`・`click`・
  `platformdirs`・`uritools` が lock と異なっていた）。`uv.lock` から生成した
  制約ファイルを Briefcase の `requirement_installer_args` で pip に渡す。
- リリース前に同梱パッケージを `uv.lock` と照合し、パッケージ一覧と全ファイルの
  SHA-256 をマニフェストとして記録するスクリプトを追加
  ([scripts/verify_bundle_deps.py](scripts/verify_bundle_deps.py))。README の
  リリース手順に組み込んだ。

### Added

- 「PDF Hanko」メニューに「設定…」（⌘,）を追加
  ([src/pdfhanko/windows/settings_window.py](src/pdfhanko/windows/settings_window.py))。
  処理量の上限を変更できる。各項目に既定値と推奨上限を表示し、推奨上限を
  超える値は警告と確認のうえで保存できる。設定は `settings.json` の `limits`
  に保存される。
- pytest による自動テストを追加 ([tests/](tests/))。`uv run pytest` で実行する。

### Fixed

- 「pyHanko --field 表示」の切り替え時に、`settings.json` のほかの項目が
  失われないよう、すべての項目を書き出すよう変更
  ([src/pdfhanko/settings.py](src/pdfhanko/settings.py))。
- PDF を開くのに失敗したとき、それまで表示していた PDF の状態が壊れる問題を修正
  ([src/pdfhanko/windows/pdf_view.py](src/pdfhanko/windows/pdf_view.py))。
  新しい PDF の確認が済むまで、表示中の PDF を閉じないようにした。

### Notes

- 初回起動時に、登録済みのハンコ・設定・ログの権限が自動で修正されます
  （ディレクトリ `0700`、ファイル `0600`）。操作は不要です。修正した件数は
  ログ（`~/Library/Logs/PdfHanko/pdfhanko.log`）に記録されます。
  権限を変更しても本人は読み書きできるため、v0.3.0 に戻してもそのまま使えます。
- `~/Library/Application Support/PdfHanko/` やログフォルダを別の場所への
  シンボリックリンクにしている場合は、ログに警告を記録したうえで、リンク先を
  そのまま使用します。リンク先のフォルダとその中のファイルの権限も、上記と
  同じく修正されます。なお、`PdfHanko/` の内側（`hankos/` 以下）を
  シンボリックリンクにすることはできません。
- 次のものはアプリから修正できません。必要に応じてご自身で対応してください。
  - Time Machine などのバックアップに残っている、以前のバージョンのデータ
    （元の権限のまま保存されています）。
  - ハンコの登録に使った元の `.p12` / `.pfx` ファイル。登録後は安全な場所に
    保管するか、不要であれば削除してください。
  - 既存ファイルに設定されている ACL（アクセス制御リスト）と拡張属性。

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

[Unreleased]: https://github.com/owlayer-com/pdf-hanko/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/owlayer-com/pdf-hanko/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/owlayer-com/pdf-hanko/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/owlayer-com/pdf-hanko/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/owlayer-com/pdf-hanko/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/owlayer-com/pdf-hanko/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/owlayer-com/pdf-hanko/releases/tag/v0.1.0
