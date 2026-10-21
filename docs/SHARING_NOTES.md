# GitHub 共有用コピーの整理記録

作成日: 2026-10-21

元の `ccg2lambda` と同じ階層に `ccg2lambda_github` を作成しました。元フォルダへの書き換えは行っていません。

## 保持したもの

- `scripts/`、英語・日本語テンプレート、実験スクリプト、既存テスト
- 独自の経路計画用テンプレートと STL 変換・正規化・集約スクリプト
- 実験入力の `ja/jsem.xml`、`ja/jsem_parsed_gold/`。後者は生成結果のような名前ですが、日本語実験スクリプトが入力として利用します
- `doc/images/`、Coq ソース、`replacement.txt`、`tactics_coq.txt`
- 元の `LICENSE` と著作権ヘッダー

## 配置の変更

| 元のパス | 共有用のパス・扱い |
| --- | --- |
| `README.md` | `README.upstream.md` に原文のまま保持。ルートの相対リンクを維持 |
| `input.txt` | `examples/input.txt` に移動 |
| `unary_rulesの内容.txt` | `docs/parser_unary_rules.txt` に移動 |
| `semantic_templates_en_test.yaml` | `en/semantic_templates_en_test.yaml` と SHA-256 が同一のため、`en/` 版へ統一 |
| `en/parser_location.txt`, `en/candc_location.txt` | 個別環境の絶対パスを含むため除外。相対パスの `.example` を追加 |
| `ja/parser_location_ja.txt`, `ja/jigg_location.txt` | 個別環境用の実設定を除外し、`.example` を追加 |

意味テンプレートや Python・シェルスクリプトのアルゴリズムは変更していません。

## 元フォルダの独自変更

元の Git index（196 ファイル）と作業ファイルの Git blob SHA-1 を比較したところ、次の 7 ファイルにローカル変更がありました。すべて変更後の内容を保持しています。

- `Dockerfile`
- `en/rte_en_mp_any.sh`
- `scripts/ccg2lambda_tools.py`
- `scripts/semantic_index.py`
- `scripts/semantic_rule.py`
- `scripts/utils.py`
- `scripts/visualization_tools.py`

主な独自追加は `ccg2lambda.sh`、`en/semantic_templates_en_test.yaml`、`en/semantic_templates_grounding.yaml`、`scripts/Canonicalization.py`、`scripts/stl_conversion.py`、`scripts/Aggregation.py`、`scripts/stl_json.py`、`scripts/visualization_tools2.py` ～ `visualization_tools6.py` です。元の Git index に登録されていないファイルも、共有対象のソースとして保持しています。

## コピーから除外したもの

| 対象 | 理由 |
| --- | --- |
| `.git/` | 元の Git 履歴・remote・ローカル設定。新規共有用の独立したソースにするため |
| `py/` | 約 3.4 GB のローカル Python 仮想環境 |
| `parsers/` の配布物・モデル | 約 1.3 GB の外部依存。別途導入する構成 |
| `plain/`, `parsed/`, `results/`, `en_plain/`, `en_parsed/`, `en_results/` | 再生成されるトークン・解析結果・HTML・ログ |
| `en/sick_intermediate_results.tgz`, `en/fracas_intermediate_results.tgz`, `ja/ja_emnlp2016_results.tgz` | 過去の結果配布アーカイブ |
| `__pycache__/`, `*.pyc`, `coqlib.vo`, `coqlib.glob` | キャッシュとコンパイル生成物 |

## 追加した共有用設定

- `.gitignore`: 仮想環境、外部モデル、生成物、個別パス、一般的な秘密設定の誤登録を抑制
- `.gitattributes`: Git を通じた登録時に、スクリプト等の改行を LF に揃える設定
- `.dockerignore`: ローカル環境や実行結果を Docker のビルド入力から除外
- `requirements.txt`: コア依存の参考一覧。動作確認済みのバージョン固定ではありません
- 日本語 README、パーサーの導入メモ、個別設定の例

## 検証範囲

コピー元から保持・移設した 208 ファイルはすべて SHA-256 が一致しました。100 MiB を超えるファイル、秘密情報の代表的パターン、個別環境のパス、除外対象の混入は検出していません。
元の `.git`、仮想環境、外部依存全体を公開する構成にはしていません。

外部環境を除外する前に独自修正の有無も調べました。NLTK の配布記録に掲載された 431 ファイルは SHA-256 が一致し、追加の Python ソースもありませんでした。depccg の小ソース 75 ファイルは [旧原典コミット](https://github.com/masashi-y/depccg/tree/263fd0afa7a619626fc2d506016625b6068bb27b) と Git blob SHA-1 が一致しました。EasyCCG / EasySRL の `unaryRules` 関連ファイルも同梱モデルアーカイブと一致したため、これらのパッチ追加は不要でした。

Python と Git がこの作業セッションの PATH に存在せず、Python 単体テスト・構文解析パイプライン・旧 Dockerfile のビルドは未実施です。依存関係の世代差と試作コードの制限はルートの [README.md](../README.md) に記載しています。
