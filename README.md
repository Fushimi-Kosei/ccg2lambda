# ccg2lambda — 経路計画・STL 向けの研究用コード

CCG 構文木と意味テンプレートから意味表現を合成する [mynlp/ccg2lambda](https://github.com/mynlp/ccg2lambda) を基に、英語の経路計画指示を扱うテンプレートと STL（Signal Temporal Logic）変換処理を追加した作業版です。

このフォルダは GitHub 共有用に整理したソース一式です。仮想環境、外部パーサー・学習モデル、実行結果、元の Git 履歴は含みません。上流の説明・引用情報は [README.upstream.md](README.upstream.md)、整理内容は [docs/SHARING_NOTES.md](docs/SHARING_NOTES.md) にあります。

## ファイル構成

| パス | 内容 |
| --- | --- |
| `ccg2lambda.sh` | 英語入力の構文解析、意味合成、HTML 出力 |
| `en/semantic_templates_en_test.yaml` | 経路計画用の研究テンプレート。編集対象の正本 |
| `en/semantic_templates_grounding.yaml` | グラウンディング用テンプレート |
| `scripts/` | 意味合成、STL 変換、可視化、既存テスト |
| `examples/input.txt` | 元の作業環境にあった短い入力例 |
| `en/`, `ja/` | 英語・日本語のテンプレート、実験用スクリプト・入力 |
| `ja/jsem_parsed_gold/` | 日本語実験の入力として使う gold 構文木 |
| `parsers/` | 外部パーサー配置先。導入説明のみ同梱 |
| `coqlib.v`, `tactics_coq.txt`, `replacement.txt` | Coq・推論処理用のソースと設定 |
| `docs/parser_unary_rules.txt` | 元の unary rules に関する研究メモ |

既存コードの関数やファイル名は維持しています。`visualization_tools2.py` などの試作も残しています。

## 実行環境と依存関係

シェルによる一連の処理は Linux / WSL を想定しています。`requirements.txt` はソースから確認したコア依存の一覧で、動作確認済みのバージョン固定ファイルではありません。

独自の STL 処理は `dataclasses` と `from __future__ import annotations` を使うため Python 3.7 以降が必要です。一方、元の意味合成コードには `nltk.compat` などの旧 API が残っています。最新の Python / NLTK での互換性や、全処理を実行できる依存バージョンの組み合わせは未検証です。

コア依存を用意する場合の例:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

STL 変換スクリプトだけなら、外部 Python 依存は `lxml` です。XML の生成には別途意味合成環境が必要です。WordNet を使う処理では次を実行します。

```bash
python -c "import nltk; nltk.download('wordnet')"
```

用途別の追加依存は次のとおりです。

- 英語の構文解析: depccg、対応する学習モデル、C&C
- 日本語の構文解析: Jigg / depccg と対応モデル
- Coq による推論: Coq。`coqc coqlib.v` でライブラリをコンパイル
- グラフ・埋め込み・評価の実験: networkx、numpy、keras / tensorflow、tqdm、pandas_ml など（対象スクリプトに応じて導入）

取得スクリプトや導入背景は [上流 README](README.upstream.md) と [parsers/README.md](parsers/README.md) を参照してください。元の `Dockerfile` は Python 3.6.3 / Debian jessie 向けの参考設定です。追加した STL スクリプトの Python 要件を満たさないため、この作業版の再現環境としては未整備です。

## パーサーの設定

以下はリポジトリのルートで実行してください。

```bash
cp en/parser_location.txt.example en/parser_location.txt
cp en/candc_location.txt.example en/candc_location.txt
```

`en/parser_location.txt` の `candc:` の後と、`en/candc_location.txt` の内容を実際の C&C ディレクトリに合わせます。`ccg2lambda.sh` を使う場合は、設定例のように `depccg:` を最後の行に置いてください。現在のスクリプトは最後に読んだパーサー名を使い、実装済みの解析関数は depccg 用です。

日本語の実験には、`ja/parser_location_ja.txt.example` と `ja/jigg_location.txt.example` をそれぞれ `.example` を外した名前へコピーし、実環境に合わせてください。個別環境の設定ファイルは `.gitignore` で除外しています。

## 英語の解析と STL 出力

必要なパーサー・モデルと、互換性のある意味合成環境を準備した後、ルートから実行します。

```bash
bash ccg2lambda.sh examples/input.txt en/semantic_templates_en_test.yaml 1
```

入力は 1 行 1 文です。独自の指示文を使う場合は `examples/input.txt` の代わりにそのファイルを指定します。同梱の短い入力例について、変換成功・期待する意味との一致は今回の整理では検証していません。

トークン化結果は `en_plain/`、構文木・意味表現は `en_parsed/`、HTML は `en_results/` に出力されます。現在のスクリプトは実行ごとに `en_parsed/` と `en_results/` を作り直します。

生成済みの意味 XML から STL 候補を JSON 出力する例:

```bash
python scripts/stl_json.py en_parsed/input.txt.depccg.sem.xml > en_results/input.stl.json
```

`stl_json.py` は `Canonicalization.py` → `stl_conversion.py` → `Aggregation.py` の順に実行し、JSON を標準出力に書き出します。個別に処理する場合:

```bash
python scripts/Canonicalization.py input.sem.xml canonicalized.json
python scripts/stl_conversion.py canonicalized.json stl.json
python scripts/Aggregation.py stl.json aggregated.json
```

## 検証と既知の制限

既存テストの入口は次です。必要に応じて WordNet と互換性のある旧依存環境を準備してください。

```bash
python scripts/run_tests.py
```

共有用整理ではコピーしたソースの一致、不要ファイルの除外、ファイルサイズ、個別環境のパス・秘密情報のパターンを確認しています。Python / パーサーを用いた動作テストは実施していません。

試作の `visualization_tools4.py`、`visualization_tools5.py`、`visualization_tools6.py` には `STL_conversion.py` という大文字名の参照が残っています。現物の `stl_conversion.py` と Linux 上で一致しません。STL 出力には上記の `stl_json.py` を使ってください。

## GitHub へ登録する例

GitHub に空のリポジトリを用意し、このフォルダをリポジトリのルートとして登録します。URL は自分のリポジトリのものへ置き換えてください。

```bash
git init -b main
git add .
git commit -m "Prepare ccg2lambda research sources for sharing"
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
```

この共有用コピーには、元フォルダの `.git` と remote 設定を引き継いでいません。

## 出自・ライセンス

上流: [mynlp/ccg2lambda](https://github.com/mynlp/ccg2lambda)。元フォルダの `master` 参照は `e3d04b13aed7abcfab08449618aacece0e6e22a0` です。この作業版には、その参照以降のローカル変更・追加が含まれます。

[LICENSE](LICENSE) と既存ソースの著作権表記を保持しています。上流の論文情報と引用案内は [README.upstream.md](README.upstream.md) を参照してください。外部パーサーやデータの利用条件は各配布元の条件に従ってください。
