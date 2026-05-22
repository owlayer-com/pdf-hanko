# Changelog

このプロジェクトの主な変更点をリリース単位で記録しています。
フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に準拠し、
バージョニングは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

(現在 v0.1.0 リリース時点。次の変更点はここに追記します。)

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

[Unreleased]: https://github.com/owlayer-com/pdf-hanko/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/owlayer-com/pdf-hanko/releases/tag/v0.1.0
