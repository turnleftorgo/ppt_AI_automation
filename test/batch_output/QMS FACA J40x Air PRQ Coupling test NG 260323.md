## **Case：** QMS FACA J40x Air PRQ Coupling test NG 260323

## **Meta Data 元數據**

- 1. 檔案名：J40x Coupling test NG

- 2. iPad機型：Air

- 3. Build：FRB

- 4. iPad機種：J40x

- 5. 製程：組裝（Assy）

- 6. 報告人：唐仕久

- 7. 關鍵字：Coupling test NG


## **問題描述：**

CD FATP find  FRB物料3pcs Coupling test NG.  F/R: 0.22% (3F/1335T)   Config :  FRB物料 HSG DQR1502000112J851  DQR1503000E12J85M  DQR1497000D12J85S。


## **問題分析：**

1.查詢不良品Trace記錄，3pcs均為B06-2F組裝線一次過站，無重測Pass記錄，返回復測Coupling均NG；
2.確認線圈卡扣結構無破損，0.32+/-0.05mm間隙尺寸實測OK；
3.拆機發現3pcs皆有Cover重工痕跡，且線圈本體存在機械刮傷；
4.判定為重工時未依規範操作，導致線圈受損未經功能檢驗即流入後段。


## **根本原因：**

1. 產生原因：Cover重工時操作不規範，導致線圈本體發生機械刮傷，造成Coupling性能異常。
2. 流出原因：重工後未執行拆解線對應工站之AIM功能檢測，且無Trace掃描防呆，致使不良品未被攔截而流入後段。


## **圍堵措施：**

1. 排查B06-2F組裝線近72H出貨之FRB物料，共約8K出貨至CD FATP，由FAE協調鎖機並執行隨線Sorting，全數重新過AIM Coupling Test站，NG品立即隔離。
2. 廠內庫存HSG DQR1502000112J851/DQR1503000E12J85M/DQR1497000D12J85S共約15K pcs全面系統扣帳，鎖2D碼禁止出貨，安排專人100%重工後重過AIM功能測試。
3. 在製品（WIP）於FQC系統端啟動強制攔截，所有經Cover重工流程之品項須100%重過AIM Coupling Test站，無Trace掃描防呆者加裝Scanning Check Rule攔截。
4. 針對重工後漏檢點，立即導入Cover重工後100% AIM功能復測工站，並由QE製作單點課程（OPL）對技工與FQC進行教育訓練，確認SOP更新並落實Trace綁定。
5. 所有經重工與全檢OK之物料，出貨外箱標示「Coupling test NG全檢OK」並註記重工日期與批號供追溯。


## **改善對策：**

1. 工程防呆：生技優化Cover重工治具，增設線圈區域物理擋塊，防止刮傷風險，並於拆解線導入Scanning Check Rule，未掃描Trace禁止過站。
2. 檢驗升級：將Cover重工後之AIM Coupling Test納入標準工站，機台程式增加防呆邏輯，未完成AIM測試者無法進入下一站。
3. 作業標準化：QE製作Cover重工單點課程（OPL）及線圈刮傷不良樣板，對技工與FQC實施教育訓練與盲測考核，確保SOP執行一致性。
4. 品管卡控：IPQC針對Cover重工工站加強巡檢頻率至1次/2H，OQC對相關料號出貨AQL抽樣標準由0.65加嚴至0.4，強化流出防堵。
