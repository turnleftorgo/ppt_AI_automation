## **Case：** QMS FACA J48x Entry MP Orion flex compass NG 260317

## **Meta Data 元數據**

- 1. 檔案名：J48x Orion flex compass NG

- 2. iPad機型：Entry

- 3. Build：MP

- 4. iPad機種：J48x

- 5. 製程：組裝（Assy）

- 6. 報告人：唐仕久

- 7. 關鍵字：Orion flex compass NG


## **問題描述：**

1.2025/12/13 FATP 裝配線Orion 功能測試NG ,測量Orion flex 對應的compass 功能NG,用CCD檢測外觀發現Flex compass區域UV 膠開裂； 2.CD FATP RTV Orion 功能NG HSG 8PCS，均發現UV膠出現輕微開裂現象。


## **問題分析：**

1.查詢不良品SN過站記錄，均為2025/12/13 M2線FATP生產，機台編號AS-821~AS-824，無Rework記錄。
2.調閱Orion flex裝配工站CCD影像，發現UV膠區域於壓合後即存在微裂紋，與後段測試NG位置對應。
3.排查裝配治具尺寸，M2線個別治具X向避位實測3.45mm（下限），與Flex來料溢膠尺寸3.3709抽測結果疊加後產生干涉。
4.確認點膠制程Z向間隙理論值0.09mm，實際因膠厚與治具公差累積導致UV膠受壓開裂。
5.判定為治具與來料公差疊加導致裝配應力集中，引發UV膠開裂，屬批量性制程風險。


## **根本原因：**

1. 產生原因：M2線個別裝配治具X向避位實測3.45mm（偏下限），疊加Flex來料溢膠尺寸3.3709超規，導致壓合時UV膠受干涉與Z向間隙不足0.09mm，引發應力集中而開裂。
2. 流出原因：Orion flex UV膠開裂未納入AOI全檢項目，且後段目視檢驗未發現微裂紋，導致不良品未能於FATP階段攔截。


## **圍堵措施：**

1. 針對2025/12/13 M2線AS-821~AS-824機台生產之嫌疑物料展開WIP與庫存清查：已出貨至FATP的物料由FAE立即駐線，配合CCD放大30倍全檢Orion flex UV膠區域，確認無開裂後方可上線；
2. 廠內庫存約38K pcs全面系統扣帳（Hold），鎖定2D碼禁止發料，安排專人使用CCD放大30倍全檢Sorting，OK品貼標「Orion Flex UV crack Sorting OK」後解鎖出貨；
3. 在製品（WIP）立即於FQC站點系統攔截，追溯SN確認生產機台，凡屬嫌疑範圍者全數退回重工站，重新壓合並過CCD外觀檢驗確認；
4. 针对流出漏检点，FQC/OQC临时导入Orion flex UV胶区域100% CCD放大检验，QE制作单点课程（OPL）培训检验员识别微裂纹，OQC抽样AQL由正常水平加严至0.65；
5. 所有经全检OK之物料，出货外箱明确标识「Orion Flex UV crack全检OK」以利追溯与客户管控。


## **改善對策：**

1. 治具防呆：生技立即優化Orion flex裝配治具，X向避位空間由3.45mm改為3.65mm（+0.2mm），Z向間隙由0.09mm提升至0.19mm，並導入壓合感測聯鎖，未達標自動報警鎖機。
2. 檢驗升級：將Orion flex UV膠開裂項目納入AOI標準檢測項，導入CCD放大30倍自動比對NG範本，全數攔截微裂紋不良；同步評估AIM導入Orion O/S compass全檢。
3. 人員培訓：QE製作UV膠開裂單點課程（OPL）與實物不良樣板，對IPQC/FQC實施盲測考核，確保微裂紋辨識能力達100%。
4. 品管加嚴：OQC針對此項不良啟動重點管控，AQL抽檢標準由0.65加嚴至0.4，巡檢頻率提升至1次/2H，並標示「Orion Flex UV crack全檢OK」追溯碼。
