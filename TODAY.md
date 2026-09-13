# TODAY

最終更新：2026-09-13

## 🔥 最優先

- [x] 個人予想（中央競馬・地方競馬・競艇）の Cursor / GitHub Actions 運用を停止する（PERSONAL_PREDICT_ENABLED=false。コードと過去データは残す。予想・結果・Excel・Drive は実行しない）
- [x] 提出用競輪のCursor連携運用を終了する（keirin-submit / keirin-ingest 停止。ChatGPT単独運用）
- [ ] CrowdWorks・Lancersで案件を探す
- [ ] noteの記事を進める

---

## 📌 進行中

- [ ] ChatGPT・Cursor・GitHubの連携環境を整える
- [ ] 利用量節約・明示指示時だけサブエージェント利用のルール：対象PR承認後のmain反映・PC同期・実行時読込み・実測効果は未確認（`docs/USAGE_POLICY.md`）

---

## ✅ 完了

- [x] 利用量節約方針と条件付き引き継ぎスキルを作業ブランチへ登録。実アプリの設定変更・自動適用は未実施
- [x] 日刊泥ママストーリーランドの参考Shorts5本を分析し、制作ガイドを作成（制作・送信なし）
- [x] 提出用競輪を個人運用シートへ切替。Chatwork送信は停止（機能は残す）
- [x] 競輪予想の内部スコア・誤り分類・学習レポートを準備する（自動実行は停止のまま）
- [x] 競輪予想をChatGPTから実行できるルール・検証ツールを準備する
- [x] 競輪予想の内部stateを既存Google Drive JSONへID上書きで残す（定期実行の空環境対策）
- [x] 提出用競輪を Cursor＝データ / ChatGPT＝最終予想 に分離する
- [x] 提出用競輪の6:00を第一予想作成までに拡張（最終・シート・ChatworkはChatGPT）
- [x] 競輪入力JSONを作成途中/完成で区別し、最終予想の補正禁止と二重送信防止を入れる
- [x] 完成済み当日JSONだけを競輪学習inboxへDrive同期する
