# 按回放任次验源的巡检交班

交班员可以在一次回放完结后再选实际读窗。档案员必须能确认这次回放确已结束、编辑事实全部交齐，以及所选窗确实来自指定任次。底稿的原位和原读代次按 README.md 的规则核定。

## 采录与封件

扩展 `handoff.capture_recording(catalog, recording_id, *, attempt_id, attest, select_windows) -> bytes`。仍可按原两个参数生成 V1 件。认证调用由可信门户侧取得并传入本次回放的非空字符串 `attempt_id`，独立回放使用不同任次号。`attest(message: bytes) -> str` 是门户侧认证回调。录制库、实际回放及这一回调属于可信采录边界。选择窗的交班员只负责指定窗，不签发门户证据。

源序号从 1 开始，按 `ReplayHandle.next_event()` 实际产出的编辑事实和读窗计数。请求动作不占序号，窗名可在同一任次重复。门户的来源证据须绑定录制号、任次、起点状态和行数、正常终点及其所覆盖的编辑事实和实际读窗。只有回放正常结束才能完成对终点的认证。回放失败或结束时还有待读请求，不能交付认证件。编辑内容沿用 V1 的 `EditFact` 字段。

`select_windows(positions)` 在门户完成回放和生成相应来源材料后调用一次。`positions` 为源序排列的实际读窗序号元组，回调返回可迭代的所选序号。允许选空、选全部或以任意次序返回选项，选项必须是互异的有效窗序号。进入选择后交件过程不再访问门户或调用 `attest`。件内所有编辑和所选窗按源序交付，未选窗正文不得装件。

认证件仍使用 `bundle.envelope.wrap_payload` 所用的外层固定字节封套。内层 JSON 含 `recording_id`、`start`、`attempt_id`、`records` 和 `source_proof`。`start` 沿用 V1 的 `state_id`、`row_count`。`records` 中每项含 `attempt_id`、`source_sequence` 及 `record`，`record` 使用 V1 的编辑或窗对象格式。可附加实现定义的来源字段，`source_proof` 的内部编码由实现决定。来源材料须涵盖本件实交记录的源序、内容与归属，足以核实正常结束和全部编辑。交付时说明新增的凭证和记录来源字段，便于重封对照件。

## 实收、核定与领取

`bundle.intake.receive(catalog_path, raw)` 沿用固定格式、摘要检查和原字节实收。实收号只标识收到的件，来源资格由核定决定。扩展 `review.decision.reconcile_bundle(catalog_path, archive_path, received_no, *, expected_recording_id, expected_attempt_id, verify_source)`。省略这三个关键字仍为 V1 调用。认证核定须同时给出三个参数，录制号、任次号及 `verify_source(message: bytes, tag: str) -> bool` 由档案员独立配置。认证件须经该模式核定。V1 件经该模式拒签。

认证核定只取指定实收号绑定的字节。须核对外部预期身份、可信起讫、编辑全量及每个交付窗的同任次来源、状态、原序号、屏位和读数。认证失败抛 `ReconcileRejected`，不产生底稿或首执。认证通过后沿用 `MissingOrigins` 和 V1 原位判据，只使用交件中实际带正文的窗。签发明细中的 `capture_sequence` 对认证件表示实际源序号。

认证成功且原位齐备时，底稿、首执及来源凭证同次落档。核定结果和 `archive.readback.read(archive_path, result_no)` 均返回原成果字段，并有 `source_proof` 属性。该属性是包含 `attempt_id` 和 `material` 的可经 JSON 往返的字典。`material` 为签发时采用的来源核验材料，包含起讫、编辑范围及实交窗绑定所需凭证，具体表示由实现决定。停用门户后仍可只凭档案库原号领取同一内容。已有库可沿用 `init` 补齐新结构，旧成果原号照领，既有 V1 调用和输出格式照常。

## 样例与运行

`source_fixture.replay_inputs()` 返回 `A`、`B` 两个任次的录制库，均使用原录制号 `scroll-complete`。A 先后两次实际读取同一首窗，做一次移位后读齐并结束。B 的第 1、3、4 窗读齐四个起点原位，第 5 事件仍有改填，第 6 事件是改填后的末窗。`auth_ports(EXAMPLE_KEY)` 提供示例用的字节认证与核验回调，分别传给可信采录和档案核定。`seed_legacy(folder)` 可在当前 V1 基线给新目录生成一对旧实收号和旧成果号，示例旧成果值为 `[0,12,5]`。

B 选择 1、3、4 应签出 `[7,11,7,13]`，再去掉第 5 编辑须拒签。去掉终点凭证、改写第 5 编辑位置，或用 A 的第 1 窗连同其来源绑定替换 B 的第 1 窗，也须拒签。B 只选 1、3 时仍可验源，原第 3 行缺证。A 选择 2、4、5 可签齐，按起点原位排列的出处序号为 `[2,2,5,4]`。

基线可用 `python3 -B -m source_fixture` 检查输入和认证回调。交付继续使用 `.pointwise-runtime.json` 的版本 1、`cli` 类型及现有参数数组格式。`setup` 保留准备命令列表，`verify` 接通原回归及验源交接场景，断言失败须非零退出。`demo` 展示实际择窗、缺编辑拒签和停源后按成果号领取底稿、首执及来源凭证。
