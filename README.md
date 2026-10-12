# 香港六合彩 V10

新引擎位於 `v10_system/`，保留原根目錄 `data/` 所有歷史資料與 V9 帳本，不重寫或追認舊資料。正式單號保持空白；研究排序、前瞻封存與公平基準分開呈現。原生輸出在 `docs/`、`site/`；既有原頁 GitHub 備援所需的明確相容格式在 `reports/`。

```sh
pip install -r v10_system/requirements.txt
python v10_runner.py init
(cd v10_system && python -m unittest discover -s tests -v)
python v10_runner.py update
python v10_runner.py verify
```

`CURRENT` 是可由普通檔案上傳的文字指標；執行環境還原本地符號連結。來源與模型說明在 `v10_system/README.md`。需 POSIX 環境（建議 Linux/GitHub Actions；Windows 使用 WSL）。

兩個既有 GitHub Actions 工作流程保留原名稱、排程、同一互斥群組與唯一 `contents: write` 權限，改以 V10 計算。沒有新增 Pages、ID token、OAuth 或憑證權限。資料、版本、帳本及三組輸出成功核對後才在同一 Git commit 發布；失敗保留線上完整舊版，不提交部分故障狀態。

原670822站點的既有載入器可能透過 `reports/` 讀取 V10。這不等同於原 Sites 重新部署，必須在實際原網址核對發布 ID。未經實際核對，不得宣稱原網址已更新。
