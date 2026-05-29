## **Case：** QMS FACA J53x Air P1 HSG Plastic overflow 2600513

## **Meta Data 元數據**

- 1. 檔案名：J53X HSG Plastic overflow

- 2. iPad機型：Air

- 3. Build：P1

- 4. iPad機種：J53x

- 5. 製程：金加（CNC）

- 6. 報告人：唐仕久

- 7. 關鍵字：HSG Plastic overflow


## **問題描述：**

FATP find 1X HSG Plastic overflow issue.F/R: 6.25%(1F/16T)  Config:M1-CB-ID3 SN: DQRGPU0000H00000GF+N


## **問題分析：**

1.查詢不良SN DQRGPU0000H00000GF+N過站記錄，為CNC1線體2025/10/14生產，機台為CNC-07，全製程一次過站無Rework。
2.調閱該機台當日投料配置，確認M1-CB-ID3與M1-CB-ID5兩種版本同時生產，存在程式混用風險。
3.排查CNC-07機台加工參數，CNC1夾使用正確程式(817-08481)，CNC2夾誤調用ID5版本程式(817-08743)，導致HSG區域應銑除區域未完全加工，產生Plastic overflow外觀NG。
4.比對OMM檢測圖檔與標準輪廓，確認NG件HSG邊緣多料尺寸超差0.12mm，與FATP不良現象一致。
5.判定因不同配置共線生產未啟動系統防呆，作業員換線時手動選程失誤，且FQC目檢未發現結構異常導致漏檢流出。


## **根本原因：**

1. 產生原因：CNC2夾位誤調用ID5版本程式(817-08743)，導致HSG區域應銑除區域未完全加工，造成Plastic overflow多料NG。
2. 流出原因：共線生產未啟動系統防呆機制，且FQC目視檢驗未發現結構異常，導致不良品漏檢流出。


## **圍堵措施：**

1. 排查CNC-07機台2025/10/14生產之M1-CB-ID3物料分佈：已出貨至FATP的約800pcs由FAE協調隨線Sorting，採用CCD放大10X目視比對標準輪廓，確認HSG邊緣無多料NG；廠內庫存約15K pcs立即系統扣帳Hold，鎖2D碼攔截，安排專人目視全檢；在製品WIP於FQC過站時系統強制攔截，全數確認結構輪廓OK後方可放行。
2. 针对Plastic overflow外觀不良，Sorting統一使用OMM圖檔比對與實配Go-NoGo檢具驗證HSG區域尺寸超差（±0.12mm），確保檢出能力。
3. FQC立即導入100%全檢該特徵，QE製作HSG結構差異單點課程（OPL）並完成全線檢驗員教育訓練，OQC抽檢AQL由II級加嚴至S-2，防止漏檢流出。
4. 所有經全檢OK之物料，出貨外箱明確標示"HSG Plastic overflow全檢OK"並註記檢驗日期與人員。


## **改善對策：**

1. 根因對策：制工針對CNC-07機台共線生產情境，在各夾位加裝程式版本探點防呆，系統自動比對料號與程式碼，版本不匹配即鎖機並觸發警報，杜絕手動選程錯誤。
2. 檢驗升級：將HSG Plastic overflow檢測導入長期管控，FQC工站增設專用Go/No-go檢具實配驗證，並導入CCD+OMM圖檔自動比對系統，實現100%輪廓自動判定與NG自動攔截。
3. 作業標準化：QE製作HSG結構差異OPL與不良樣板，標註ID3與ID5版本關鍵輪廓差異，對CNC作業員、IPQC及FQC全員實施教育訓練與盲測考核，合格方可上崗。
4. 品管卡控：OQC針對此異常項目啟動加嚴檢驗，抽檢水準由AQL II級提升至S-2，重點稽核HSG區域結構一致性，防堵漏檢風險。
