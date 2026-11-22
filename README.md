# 东岬港巡检交班档案

东岬港二号泊位资料班从确定性录制巡读虚拟表格。交班员封存实际读窗及屏间编辑，离线档案员核定班次起点的原读数，次班凭成果号领取已签底稿。补证岗使用缺证原位清单定位回查目标。

## 运行

在项目根目录使用 Python 3.11。运行清单中的标准回归入口由控制台物化。

```text
python3 -B check_project.py
python3 -B handoff.py demo
```

Demo 在独立的临时目录中初始化两座库，实收两份录制交接件，演示原第 3 行缺证，以及补读齐备后的原序签发和重新领取。也可以逐步运行。下例使用新建目录，实收和成果编号以命令实际输出为准。

```text
python3 -B handoff.py init work
python3 -B handoff.py capture work scroll-complete work/shift.bundle
python3 -B handoff.py receive work work/shift.bundle
python3 -B handoff.py reconcile work 1
python3 -B handoff.py read work 1
```

`init` 安装缺失的录制清单并建立独立的实收和档案库。可重复执行，保留已存在的录制文件及兼容库内的数据。遇到不兼容的受管表会报错。`capture` 需要一个尚不存在的输出文件。离线命令只使用实收和档案库。`reconcile` 遇到合法但缺证的件时输出全部原位并以状态码 2 结束。其他业务拒绝以状态码 1 结束。

## 数据与接口

1. `portal.recording.load_recordings(path)` 读取 `recordings.json`。`portal.replay.open_shift(catalog, recording_id)` 返回起点状态、起点行数和独立回放句柄，未知录制抛出 `KeyError`。`ReplayHandle.next_event()` 返回编辑事实或读窗，录制结束时返回 `None`。录制中的 `request` 安排行位范围，`read` 从实际发生时的表读取该范围。
2. `capture.session.start_capture(recording_id, state_id, row_count)` 建立会话。`capture_window(session, event)` 接受单次实读或编辑，非法事件抛出 `ValueError` 并保留之前的有效状态。调用 `finish_capture(session)` 结束会话。`bundle.issue.seal(session)` 对结束会话生成固定字节，未结束时抛出 `ValueError`。
3. `bundle.intake.receive(catalog_path, raw)` 核对内层格式、录制身份及内容摘要，实收成功后返回整数实收号。拒收抛出 `IntakeRejected`。摘要用于检测固定件内容变化。实收号绑定接收的原始字节，相同录制号可以有多个实收号。
4. `review.decision.reconcile_bundle(catalog_path, archive_path, received_no)` 只使用指定实收件。成功返回 `SignedDraft`，包含原序明细和首执。合法但覆盖不足返回 `MissingOrigins`，其中列出所有缺证原位。缺件、断链、矛盾和签存失败抛出带 `code` 的 `ReconcileRejected`。
5. `archive.readback.read(archive_path, result_no)` 返回原签件和首执，成果不可领时抛出 `UnavailableResult`。原位和实读屏位分别存储，门户后续编辑或停用后仍能定位签发所依据的原窗。

读数为整数毫米，零有效，空值和小数属于非法输入。行位从 1 开始，移位的目标位是操作完成后的位置。状态号和窗号均为非空文本。采录保留同一屏位的各次观察，事件序号从 1 开始，可与实际状态、窗号和屏位一起定位出处。插入行没有起点原位，移位延续行身份，删除前已采的原读继续有效，改填后原读资格结束，即使写回同值。合格重复观察须一致，按采录顺序选择最早出处。零行起点使用同一覆盖规则，签出空明细和首执。

`scroll-missing` 的起点是 `[7,11,7,13]`。末行移首后，原第 3 行来到第 4 屏位，改填后读到的 19 mm 属于新读数，因此原第 3 行缺证。`scroll-complete` 多一次改填前第 4 屏位的实读，原序签出 `[7,11,7,13]`，其中第三行指向该补读窗的第 4 屏位。
