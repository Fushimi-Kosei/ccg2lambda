# 外部パーサーとモデル

このディレクトリには、利用する CCG パーサーと学習モデルを別途配置します。
元の作業環境にあった C&C、EasyCCG、EasySRL、Jigg とそのモデルは、共有用コピーには含めていません。
ライセンスや入手条件は各配布元に従ってください。

上流の導入説明は [README.upstream.md](../README.upstream.md) を参照してください。
既存の取得スクリプトと Dockerfile は過去の環境向けで、現在の配布先への接続・ビルドは未検証です。

`ccg2lambda.sh` の現在の実装は depccg による解析と C&C による注釈を使用します。
depccg 本体と、そのバージョンに対応する英語 ELMo モデルも別途必要です。
設定ファイルの作り方は [共有用 README](../README.md) を参照してください。

元の仮想環境の depccg メタデータは `2.0.3.2` でした。小ソース 75 ファイルは
[旧コミット 263fd0a](https://github.com/masashi-y/depccg/tree/263fd0afa7a619626fc2d506016625b6068bb27b)
と Git blob SHA-1 が一致しています。導入環境を再構成する際の参照情報です。
現行の depccg がこのコードの CLI と互換であることは確認していません。
