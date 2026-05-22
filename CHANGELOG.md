# Changelog

このプロジェクトの主な変更点をリリース単位で記録しています。
フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に準拠し、
バージョニングは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

### Added
- バージョン情報を `pdfhanko.__version__` から取得可能に
- 「PDF Hanko について」(About) ダイアログ — バージョン・ライセンス・OSS 帰属を表示
- 「ヘルプ」メニュー — GitHub の README を既定ブラウザで開く
- エラーログ出力 — `~/Library/Logs/PdfHanko/pdfhanko.log` (WARNING 以上、ローテーション付き)
- 仮アプリアイコン（朱色の丸印 + 「印」）

## [0.1.0] - 未リリース

初回リリース予定の機能セット。

### Added
- ハンコ登録・編集・削除（印影画像 + PKCS#12 証明書 + 名前・サイズ・メモ）
- PDF 表示（pypdfium2、ページ送り、72 DPI 正規化）
- ドラッグでの押印位置指定 + 半透明プレビュー
- PAdES 準拠の電子署名（PyHanko、async API）
- 複数押印 / 既存署名済み PDF への追加押印（incremental update）
- ハイブリッド xref を含む PDF への対応 (`strict=False`)
- macOS 向け `.app` バンドル + `.dmg` パッケージング (Briefcase, ad-hoc 署名)
- 終了時のリソース明示解放 (segfault 抑制)

[Unreleased]: https://github.com/owlayer-com/pdf-hanko/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/owlayer-com/pdf-hanko/releases/tag/v0.1.0
