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

认证交接可用 `certified-capture`。它需要一个门户认证密钥，并在回放结束后按 `--select` 选定实际窗源序号；`reconcile` 用同一密钥独立核定，并给出预期录制号与任次号：

```text
python3 -B handoff.py certified-capture work scroll-complete work/shift.bundle \
    --attempt-id B --select 1,3,4 --key "$PORTAL_KEY"
python3 -B handoff.py receive work work/shift.bundle
python3 -B handoff.py reconcile work 1 --recording-id scroll-complete --attempt-id B --key "$ARCHIVE_KEY"
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

## 按回放任次验源

`SOURCE_HANDOFF.md` 描述认证交接。要点：

1. `handoff.capture_recording(catalog, recording_id, *, attempt_id, attest, select_windows)`。两个位置参数仍是 V1 采录。给出三个关键字后，可信门户先完整回放，逐事件 `attest`，再调用一次 `select_windows(实际窗序号元组)`；选定后不再访问门户或 `attest`。回放未正常结束、仍有待读请求或编辑不全都不出认证件。
2. 认证件内层含 `recording_id`、`start`、`attempt_id`、`records`、`source_proof`。每条记录带 `attempt_id`、`source_sequence`、`source_evidence` 及 V1 的 `record`。所选窗正文按源序装入，未选窗正文不装件；编辑事实全部装入。
3. `source_proof.material` 是门户在回放中生成的来源材料：录制号、任次、起点状态与行数、正常终点、全部编辑事实与全部实际窗的绑定摘要；`proofs` 是按源序排列的逐事件认证标签，`end_proof` 是终点标签。门户按“此前链值 + 本事件”链式认证，删改任一编辑或换窗即断链。
4. `review.decision.reconcile_bundle(..., expected_recording_id=, expected_attempt_id=, verify_source=)` 必须三项齐给才走认证核定；V1 件在此模式 `uncertified_bundle` 拒签。缺任次、窗出处不符、终点无证或编辑缺失均 `source_unverified` 拒签且不落档。通过后仍只用交件中带正文的窗按 V1 判据核定原位。
5. 认证签发把 `source_proof`（含 `attempt_id` 与 `material`）同次写入档案。`read` 返回的成果带同名属性，可 JSON 往返；停用门户后仍凭原号领取。
6. 已存在旧库经 `init` 自动补 `source_proof` 列，旧成果原号照领，V1 调用与输出格式不变。
