# 香港六合彩官方資料核驗系統 v9

這是與舊引擎分離的新系統。只從香港賽馬會的公開結果介面讀取已公布攪珠；`data/hkjc_verified_v9.csv` 從 2003 年起逐月建立，完全不從舊 CSV 補數。2003 年起保守限定於現行 49 球賽制；歷史更早的不同球數年代不參與同一機率模型。

## 重要更正

舊庫 `data/official_marksix.csv` 的多數紀錄標成「mark6six_archive_crosscheck_hkjc」，但舊匯入程式未執行馬會交叉核對；這個來源標籤不成立。舊模型還將 2002 年 7 月前不同球數的開獎史與現行 49 球制混算。舊版資料、封存紀錄僅保留供追溯，不作新模型輸入或新系統實戰成績；舊版程式已從根目錄入口移除，所有相容入口只呼叫 `v9`。初次重建（2026-10-09）取得的 3,323 筆官方結果與舊庫同日期號碼比對一致，但這不會追認舊標籤。

## 新流程

```powershell
python -m v9.watchdog
python -m v9.verify
python -m unittest tests.test_v9 -v
python -m v9.full_official_audit
```

第一次沒有新資料庫時會直接向馬會逐月重建；其後每次核對最近六個月及最近 20 期。來源失敗或同日內容衝突即停止發布，不用第三方結果補缺。`data/hkjc_verified_v9_manifest.json` 保存來源、期數、抓取時間及檔案 SHA-256；`data/v9_forecast_events.jsonl` 使用附加式雜湊鏈分開封存預測與事後結算，不回填成績。

`v9/model.py` 的五個固定候選模型只產生相對排序分數，不把它當作真實中獎機率。前 400 期選模型，後 120 期固定評估並做多重比較校正；回顧成績與開獎前封存實戰分開顯示。未通過統計與前瞻驗證時，不顯示高信心或必中。下一期日期若未從官方取得，不編造日期。

`full_official_audit` 會另行逐月重新抓取 2003 年至今的馬會結果，逐筆比對資料庫，將數量、缺漏、衝突及資料 SHA-256 寫入公開審計檔。戰報只會在該審計的資料 SHA-256 與當前資料一致時標示全史核對通過；後續新增開獎時，舊審計不會冒充新資料的核對。戰報另公開最近 60 期的正碼次數、上一期同模型排序及封存實戰成績；重複號碼不代表更高的中獎機率。

公開戰報為 `https://hong-kong-marksix-report.ping-shen670822.chatgpt.site/report/latest_battle_report.html`，備援為 `https://pingshen670822.github.io/hong-kong-marksix-ironlaw/latest_battle_report.html`。主流程每小時錯峰檢查，開獎時段密集更新；第二層除主流程失敗觸發外，也獨立檢查戰報逾時與健康狀態。GitHub 排程可能延遲或漏觸發，不能聲稱更新時間有絕對保證。手機「手動核對」是無快取讀取雲端版本；真正雲端重算需透過 GitHub Actions，頁面不持有憑證。

六合彩屬隨機攪珠；統計研究不保證中獎。未滿 18 歲不得投注，請量力而為。
