# 資料來源及隔離

- `hkjc_verified_v9.csv`：新系統唯一的開獎模型輸入，由香港賽馬會公開 GraphQL 結果介面逐月取得；`hkjc_verified_v9_manifest.json` 保存 SHA-256 與來源資訊。
- `v9_forecast_events.jsonl`：新系統開獎前預測及事後結算的附加式雜湊鏈。
- `official_marksix.csv`：**舊版未驗證來源標示的歷史檔，僅供追溯，不得當作官方核驗檔或新系統輸入。** 多數列的 `mark6six_archive_crosscheck_hkjc` 標籤是舊程式直接寫入，並非當時已完成馬會交叉核對。
- `prediction_history.json`：舊引擎封存，與新系統的實戰成績完全分開。
