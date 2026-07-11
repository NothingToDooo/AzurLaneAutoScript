# ALAS CnOCR 结构化结果 P0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不替换现有 CnOCR、不批量改变旧调用点的前提下，保留模型原始文字与置信度，建立可区分合法零值和识别失败的结构化数字结果、严格 Counter/Duration 解析、受控失败样本闭环，并在 `MeowfficerBuy.meow_get_buy_count()` 跑通第一条纵向切片。

**Architecture:** 在轻量 `module/ocr/result.py` 中定义结果契约，由 `AlOcr` 在第三方边界严格转换 CnOCR 字典；`Ocr` 只增加受保护的原始推理入口，`Digit`、`DigitCounter`、`Duration` 各自提供类型明确的 `recognize()`，旧 `.ocr()` 暂时维持历史语义。失败样本由独立 `OcrFailureStore` 同步、原子、去重、限额写入；只有调用方显式传入 store 且 `Error_SaveError` 开启时才保存。首个消费者仅迁移指挥喵购买状态。

**Tech Stack:** Python 3.14.6、uv、CnOCR 2.3.3、ONNX Runtime、NumPy、Pillow、pytest、Ruff、ty、Windows。

## Global Constraints

- 当前生产模型继续使用 `densenet_lite_136-gru`；不新增或下载 PP-OCR 等模型，不改变依赖。
- 现有 `.ocr()` 返回类型和 19 个左右的 `DigitCounter` 旧调用点不批量迁移；只有 `meow_get_buy_count()` 改用结构化接口。
- 新 `DigitCounter.recognize()` 使用完整匹配并把 `current > total` 判为失败；旧 `DigitCounter.ocr()` 在本阶段继续保留历史截断行为，避免未迁移调用方静默改变。
- score 只记录，不设置经验阈值；结构格式和业务约束决定 `valid`。
- 失败图片只对白名单式、显式传入 store 的固定数字 ROI 保存；一般文本 OCR 不自动采集，不能把小 ROI 交给只适配 1280×720 全屏的 `handle_sensitive_image()`。
- 失败存储服从 `Error_SaveError`，落在已被 `.gitignore` 忽略的 `./log/ocr_failure/`。
- 本阶段不做模型会话共享、缓存、张量 batch、后台预热、ReplayDevice 扩展、Operation 提取或模型替换。
- 不添加 `from __future__ import annotations`；注释、docstring 和日志说明使用中文。
- 所有行为先写测试并确认按预期失败，再实现；每个任务独立验证并使用 `english-tag: 中文说明` 提交。

---

### Task 1: 在 CnOCR 边界保留原始文字与 score

**Files:**
- Create: `module/ocr/result.py`
- Modify: `module/ocr/al_ocr.py`
- Create: `tests/test_ocr_result.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class RawOcrResult:
    text: str
    score: float


class RecognitionFailureReason(StrEnum):
    EMPTY_TEXT = "empty_text"
    FORMAT_MISMATCH = "format_mismatch"
    CURRENT_EXCEEDS_TOTAL = "current_exceeds_total"
    UNEXPECTED_TOTAL = "unexpected_total"
    TIME_COMPONENT_OUT_OF_RANGE = "time_component_out_of_range"


@dataclass(frozen=True, slots=True)
class RecognitionResult[T]:
    raw_text: str
    normalized_text: str
    score: float
    value: T | None
    valid: bool
    reason: RecognitionFailureReason | None
    latency_seconds: float
    profile: str
    model: str
```

`RecognitionResult.__post_init__()` 必须锁定以下不变量：`profile.strip()`、`model.strip()` 非空，score 有限且位于 `[0, 1]`，latency 有限且 `>= 0`；成功结果必须有非 `None` value 且无 reason，失败结果必须 value 为 `None` 且有 reason。这样测试 fake 不能绕过第三方边界制造 NaN 结果。

`AlOcr` 新增：

```python
@property
def model_name(self) -> str: ...

@staticmethod
def _extract_raw_result(result: object) -> RawOcrResult: ...

def ocr_for_single_lines_raw(self, img_list, batch_size=1) -> list[RawOcrResult]: ...
def atomic_ocr_for_single_lines_raw(self, img_list, cand_alphabet=None) -> list[RawOcrResult]: ...
```

第三方字典必须有 `text: str` 和有限、位于 `[0, 1]` 的实数 `score`；缺字段统一抛 `TypeError`，错误类型或范围抛 `TypeError`/`ValueError`，不再静默变成空字符串，也不泄漏 `KeyError`。现有 `ocr_for_single_line(s)` 和 `atomic_ocr_for_single_line(s)` 继续返回字符串，只从 raw 结果投影 `.text`。当前 `AlOcr.ocr()` 也已经投影为 `list[str]`；P0 保持这一现状，不借机恢复 CnOCR 检测结果中的 position/cropped image，也不把单行 DTO 错当成完整检测结果。

`AlOcr.__init__()` 在不加载模型的情况下保存规范化后的 `self._model_name = self._normalize_model_name(model_name)`；`model_name` 属性必须返回实际模型名 `densenet_lite_136-gru`，不能返回构造别名 `densenet-lite-gru`，也不能触发 `ensure_loaded()`。

- [x] **Step 1: 写 DTO 不变量、CnOCR 字典转换和非法 payload 测试**

```python
def test_extract_raw_result_preserves_text_and_score() -> None:
    result = AlOcr._extract_raw_result({"text": "14/15", "score": 0.875})

    assert result == RawOcrResult(text="14/15", score=0.875)


@pytest.mark.parametrize(
    "payload",
    [None, "14/15", {}, {"text": 14, "score": 0.9}, {"text": "14/15", "score": float("nan")}],
)
def test_extract_raw_result_rejects_malformed_payload(payload: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        AlOcr._extract_raw_result(payload)
```

- [x] **Step 2: 运行测试并确认因结果模块/raw API 不存在而失败**

Run: `uv run pytest tests/test_ocr_result.py -q`

- [x] **Step 3: 实现轻量 DTO 和严格第三方边界**

`module/ocr/result.py` 不得导入 `cnocr`、OpenCV 或 Pillow，确保 `module/ocr/ocr.py` 运行时引用结果类型不会破坏现有重依赖延迟加载。`_extract_raw_result()` 使用 `numbers.Real` 接受 NumPy 实数，但显式拒绝 `bool`，并统一转成 Python `float`。

- [x] **Step 4: 写 raw 批量/空列表及旧单张、批量字符串投影测试**

测试通过 monkeypatch `CnOcr.ocr_for_single_lines`、`AlOcr.set_cand_alphabet` 并把 `AlOcr._model_loaded` 置为 `True` 隔离真实模型会话；导入 `al_ocr.py` 本身仍会导入 CnOCR，不能把它误写成轻量测试。现有 `ocr_for_single_line()` 自己从 raw batch 的第一项投影 `.text`，不能调用会动态分派回字符串方法的 `super().ocr_for_single_line()`。P0 只新增生产调用需要的两个 batch raw 入口，不预建无消费者的 raw 单张包装。

- [x] **Step 5: 运行定向测试、Ruff、ty 和差异检查**

Run:

```powershell
uv run pytest tests/test_ocr_result.py -q
uv run ruff check module/ocr/result.py module/ocr/al_ocr.py tests/test_ocr_result.py --no-cache
uv run ruff format --check module/ocr/result.py module/ocr/al_ocr.py tests/test_ocr_result.py
uv run ty check module/ocr/result.py module/ocr/al_ocr.py
git diff --check
```

- [x] **Step 6: 提交**

Commit: `refactor: 保留CnOCR原始识别结果`

---

### Task 2: 建立结构化 Digit、Counter 与 Duration 解析

**Files:**
- Modify: `module/ocr/ocr.py`
- Modify: `tests/test_ocr_result.py`

**Interfaces:**

```python
type DigitCounterValue = tuple[int, int, int]


class _OcrEngine(Protocol):
    @property
    def model_name(self) -> str: ...

    def atomic_ocr_for_single_lines(self, image_list: list[np.ndarray], cand_alphabet=None) -> list[str]: ...

    def atomic_ocr_for_single_lines_raw(
        self,
        image_list: list[np.ndarray],
        cand_alphabet=None,
    ) -> list[RawOcrResult]: ...


@dataclass(frozen=True, slots=True)
class _OcrInference:
    raw_image: np.ndarray
    processed_image: np.ndarray
    area: tuple[int, int, int, int] | None
    result: RawOcrResult


@dataclass(frozen=True, slots=True)
class _OcrInferenceBatch:
    items: tuple[_OcrInference, ...]
    latency_seconds: float
    model: str


class Ocr:
    @property
    def cnocr(self) -> _OcrEngine: ...


class Digit(Ocr):
    def recognize(self, image, direct_ocr=False) -> RecognitionResult[int] | list[RecognitionResult[int]]: ...


class DigitCounter(Ocr):
    def recognize(
        self,
        image,
        direct_ocr=False,
        *,
        expected_total: int | None = None,
    ) -> RecognitionResult[DigitCounterValue]: ...


class Duration(Ocr):
    def recognize(self, image, direct_ocr=False) -> RecognitionResult[timedelta] | list[RecognitionResult[timedelta]]: ...
```

`Ocr` 增加受保护的单行原始推理入口并返回 `_OcrInferenceBatch`，不用多个可能错位的平行列表。batch 只保存一次整批调用耗时和模型名；每个公开结果复制同一个 batch latency，并在文档中明确它不是单 ROI 独立耗时。不把 NumPy 数组塞进公开 `RecognitionResult`。Digit 和 Duration 保持旧接口的单 ROI 标量/多 ROI 列表形状；`DigitCounter.recognize()` 明确只接受一个 ROI，多 ROI 立即 `ValueError`，不再静默取第一项。

解析规则：

- Digit：先检查 raw text 是否为空；非空时调用动态分派的 `self.after_process(raw.text)`，保留等级、价格、活动点数等现有子类修正；捕获整数转换产生的 `ValueError`，并拒绝非 int 返回。成功结果的 `normalized_text = str(value)`，字符串 `"0"` 是 value 0 的成功结果。自行覆写旧 `.ocr()` 并改变语义的 Digit 子类不会自动获得等价新语义，P0 不迁移这些调用者。
- Counter：必须在全部 `after_process()` 修正完成后用 `fullmatch(r"(\d+)/(\d+)")`；空串、部分匹配、多个斜杠分别失败；`current > total` 为 `CURRENT_EXCEEDS_TOTAL`。可选 `expected_total` 只表达调用点已经明确知道的业务上限，解析出的 total 不一致时为 `UNEXPECTED_TOTAL`；默认 `None` 不给其他 Counter 添加领域假设。成功 value 仍是 `(current, total - current, total)`。
- Duration：只接受完整 `H:MM:SS`/`HH:MM:SS` 或完全紧凑的 `HMMSS`/`HHMMSS` 两个分支，拒绝 `01:3000`、`0130:00` 等混合缺冒号形式；分钟或秒大于 59 为 `TIME_COMPONENT_OUT_OF_RANGE`。
- score 属于 raw text，不因规范化或解析修正而变化；profile 使用显式 name，否则使用 OCR 类名；model 使用 `AlOcr.model_name`；耗时使用 `time.perf_counter()`。
- 三个结构化解析器各自提供不执行推理的受保护 `_parse_result(raw, *, latency_seconds, model, ...)`，`recognize()` 只负责准备/推理后调用纯解析边界。这既避免 parser 测试加载模型，也允许失败 bundle 用 metadata 离线重放同一解析结果。
- 新结构化调用沿用现有 OCR 日志，但属性中额外包含原始 score、valid 和 reason；首个 meow 切片的成功与失败 score 因而进入标准日志，可用于提取分布。P1 才增加全局 profile 调用量、耗时和宽度统计，本阶段不建立指标数据库。

`tests/test_ocr_result.py` 使用下面的文件级 scaffold；所有 helper 必须在测试文件中真实定义，不能依赖伪代码名称：

```python
TEST_AREA = (0, 0, 4, 4)
TEST_IMAGE = np.zeros((4, 4, 3), dtype=np.uint8)


class _FakeEngine:
    model_name = "densenet_lite_136-gru"

    def __init__(self, text: str, score: float) -> None:
        self.result = RawOcrResult(text=text, score=score)

    def atomic_ocr_for_single_lines_raw(self, image_list, cand_alphabet=None):
        del cand_alphabet
        return [self.result for _ in image_list]

    def atomic_ocr_for_single_lines(self, image_list, cand_alphabet=None):
        del cand_alphabet
        return [self.result.text for _ in image_list]


class _TestDigit(Digit):
    def __init__(self, engine: _FakeEngine, buttons=TEST_AREA) -> None:
        self._engine = engine
        super().__init__(buttons, name="TEST_DIGIT")

    @property
    def cnocr(self) -> _FakeEngine:
        return self._engine


class _TestCounter(DigitCounter):
    def __init__(self, engine: _FakeEngine, buttons=TEST_AREA) -> None:
        self._engine = engine
        super().__init__(buttons, name="TEST_COUNTER")

    @property
    def cnocr(self) -> _FakeEngine:
        return self._engine


class _TestDuration(Duration):
    def __init__(self, engine: _FakeEngine, buttons=TEST_AREA) -> None:
        self._engine = engine
        super().__init__(buttons, name="TEST_DURATION")

    @property
    def cnocr(self) -> _FakeEngine:
        return self._engine


def make_digit(text: str, *, score: float = 0.9, buttons=TEST_AREA) -> _TestDigit:
    return _TestDigit(_FakeEngine(text, score), buttons=buttons)


def make_counter(text: str, *, score: float = 0.9, buttons=TEST_AREA) -> _TestCounter:
    return _TestCounter(_FakeEngine(text, score), buttons=buttons)


def make_duration(text: str, *, score: float = 0.9, buttons=TEST_AREA) -> _TestDuration:
    return _TestDuration(_FakeEngine(text, score), buttons=buttons)


def require_single[T](
    result: RecognitionResult[T] | list[RecognitionResult[T]],
) -> RecognitionResult[T]:
    assert not isinstance(result, list)
    return result
```

实现时给 fake 方法补齐与生产 Protocol 相同的窄类型标注；若 ty 对测试 duck type 报错，修正 fake 签名，不得用 `Any` 或全局 ignore 绕过。

- [x] **Step 1: 写合法零、严格 Counter、Duration 范围及字段保留测试**

```python
def test_digit_recognize_distinguishes_zero_from_empty() -> None:
    zero = require_single(make_digit("0", score=0.91).recognize(TEST_IMAGE))
    empty = require_single(make_digit("", score=0.12).recognize(TEST_IMAGE))

    assert (zero.valid, zero.value, zero.reason) == (True, 0, None)
    assert (empty.valid, empty.value, empty.reason) == (False, None, RecognitionFailureReason.EMPTY_TEXT)


def test_counter_recognize_rejects_current_above_total() -> None:
    result = make_counter("99/15", score=0.99).recognize(TEST_IMAGE)

    assert result.valid is False
    assert result.value is None
    assert result.reason is RecognitionFailureReason.CURRENT_EXCEEDS_TOTAL
    assert result.raw_text == "99/15"
    assert result.score == 0.99


@pytest.mark.parametrize("text", ["x14/15", "14/15/", "1/2/3"])
def test_counter_recognize_requires_full_match(text: str) -> None:
    assert make_counter(text).recognize(TEST_IMAGE).reason is RecognitionFailureReason.FORMAT_MISMATCH


@pytest.mark.parametrize("text", ["01:60:00", "01:00:60"])
def test_duration_recognize_rejects_invalid_components(text: str) -> None:
    result = require_single(make_duration(text).recognize(TEST_IMAGE))
    assert result.reason is RecognitionFailureReason.TIME_COMPONENT_OUT_OF_RANGE
```

另参数化验证 `1:30:00`、`01:30:00`、`13000`、`013000` 成功，`01:3000`、`0130:00` 为 `FORMAT_MISMATCH`。

- [x] **Step 2: 写旧接口特征测试并确认新严格语义不会外溢**

```python
def test_legacy_counter_ocr_keeps_clamping_until_callers_migrate() -> None:
    counter = make_counter("99/15")

    assert counter.ocr(TEST_IMAGE) == (15, 0, 15)
    assert counter.recognize(TEST_IMAGE).valid is False
```

同时覆盖新 Digit 的多 ROI 结果列表，以及旧 `Ocr.ocr()` 单 ROI 返回标量、多 ROI 返回列表、空 Counter 返回 `(0, 0, 0)`，防止受保护推理入口改变历史形状。

- [x] **Step 3: 运行测试并确认因 `recognize()` 和严格结果不存在而失败**

Run: `uv run pytest tests/test_ocr_result.py -q`

- [x] **Step 4: 实现最小原始推理入口和三个结构化解析器**

测试 fake engine 同时实现旧 `atomic_ocr_for_single_lines()` 与新 `atomic_ocr_for_single_lines_raw()`；测试子类覆写 `cnocr` 属性返回 fake，不修改全局 `OCR_MODEL` 缓存，也不得实例化真实 CnOCR。Counter 调用 `self.after_process(raw.text)` 后再 fullmatch，以保留 `StockCounter`、`MetaDigitCounter`、`OcrDormFood` 等已有文本修正顺序。

P0 明确保留两条解析路径并允许少量重复：旧 `.ocr()` 继续使用宽松 search/clamp 或旧 Duration 解析，新 `.recognize()` 独立使用 fullmatch/范围校验；在旧调用方迁移完成前，禁止为了复用让 `.ocr()` 简单投影 `.recognize().value`。

- [x] **Step 5: 增加 Counter 子类后处理在 fullmatch 前生效的特征测试**

至少选择一个纯文本修正 Counter 子类或测试专用子类，把 `"1415"` 修成 `"14/15"`，验证新接口得到 `(14, 1, 15)`；再用测试 Digit 子类把非空 raw 修正成整数，证明 `recognize()` 走 `self.after_process()`，同时锁定旧 Duration 仍接受其历史混合缺冒号输入。不得批量迁移这些生产调用点。

monkeypatch `module.ocr.ocr.logger.attr` 捕获一次成功和一次失败的新结构化调用，断言日志属性包含 profile、score、valid、reason；这锁定 score 不只停留在瞬时对象中，而会进入现有持久日志供后续提取分布。

- [x] **Step 6: 运行定向检查并提交**

Run:

```powershell
uv run pytest tests/test_ocr_result.py tests/test_ocr_options.py tests/test_raid.py -q
uv run ruff check module/ocr/result.py module/ocr/ocr.py tests/test_ocr_result.py --no-cache
uv run ruff format --check module/ocr/result.py module/ocr/ocr.py tests/test_ocr_result.py
uv run ty check module/ocr
git diff --check
```

Commit: `feat: 增加数字OCR结构化解析`

---

### Task 3: 建立原子、去重、限额的失败样本存储

**Files:**
- Create: `module/ocr/failure_store.py`
- Create: `tests/test_ocr_failure_store.py`

**Interfaces:**

```python
class OcrFailureRecordStatus(StrEnum):
    SAVED = "saved"
    DUPLICATE = "duplicate"
    LIMIT_REACHED = "limit_reached"
    TOO_LARGE = "too_large"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class OcrFailureRecordResult:
    status: OcrFailureRecordStatus
    digest: str
    directory: Path | None


class OcrFailureStore:
    def __init__(
        self,
        root: Path = Path("./log/ocr_failure"),
        *,
        max_total_samples: int = 256,
        max_samples_per_profile: int = 64,
        max_total_bytes: int = 64 * 1024 * 1024,
        max_new_samples_per_process: int = 16,
    ) -> None: ...

    def record[T](
        self,
        result: RecognitionResult[T],
        *,
        raw_image: np.ndarray,
        processed_image: np.ndarray,
        area: tuple[int, int, int, int] | None,
        alphabet: str | None,
        letter: tuple[int, int, int],
        threshold: int,
        expected_total: int | None = None,
    ) -> OcrFailureRecordResult: ...


class OcrFailureRecorder(Protocol):
    def record[T](
        self,
        result: RecognitionResult[T],
        *,
        raw_image: np.ndarray,
        processed_image: np.ndarray,
        area: tuple[int, int, int, int] | None,
        alphabet: str | None,
        letter: tuple[int, int, int],
        threshold: int,
        expected_total: int | None = None,
    ) -> OcrFailureRecordResult: ...


OCR_FAILURE_STORE = OcrFailureStore()
```

目录固定为：

```text
log/ocr_failure/<profile>/<sha256>/
├── raw.png
├── processed.png
└── metadata.json
```

存储规则：

- `__init__()` 不创建目录；第一次 record 时才创建 profile 目录。P0 不扫描或清理其他进程可能正在使用的 `.tmp`；每次调用只清理由自己创建的临时 bundle，崩溃残留留给后续带 PID/年龄判断的维护工具处理。
- profile 只接受 `[A-Za-z0-9_.-]` 且长度不超过 64，拒绝空值和路径穿越。
- digest 使用版本化 canonical JSON 上下文加连续的预处理 ROI 字节；上下文包含 profile、model、reason、raw/normalized text、area、alphabet、letter、threshold、expected_total、processed dtype/shape。
- digest 明确排除时间、score 和 latency，避免同一推理输入因浮点抖动重复入库；raw ROI 不参与摘要，同一预处理输入只保留第一份 raw 代表样本。
- 全局最多 256 份/64 MiB，每 profile 最多 64 份，每个 ALAS 子进程生命周期最多新增 16 份；duplicate 不消耗进程预算。达到上限时拒绝新写入，不在 P0 自动删除用户已积累的样本。全局计数和字节统计只读取名称为 64 位十六进制且含有效 metadata 的完整 bundle，未知目录不计数也不删除。
- 使用 Pillow 把数组编码到内存，发布前先计算新 bundle 字节数；单份已经超过全局字节预算时返回 `TOO_LARGE`。随后用 `module/base/atomic.py` 的 `to_tmp_file()` 生成本次调用独占目录名、用 `file_write()` 写 bundle，三个文件全部成功后以 `atomic_replace()` 一次发布；异常只用 `folder_rmtree()` 清本次临时目录。
- 两个进程同时提交同一 digest 时，第二个发布若发现 final 已完整出现，清理自己的临时目录并返回 `DUPLICATE`，不能把它当成存储故障，也不能覆盖第一份 bundle。
- P0 的全局数量/字节检查是发布前的保守检查，不引入跨进程锁；并发不同 digest 最多可按同时在途写入数小幅越过全局阈值。每进程新增上限仍生效，后续只有真实多配置运行证明需要时才增加锁文件协议。
- JSON 使用 UTF-8、`ensure_ascii=False`、`sort_keys=True` 和结尾换行，包含 schema version、带时区 captured_at、全部结构化结果字段、area、alphabet、letter、threshold、expected_total、raw/processed shape 与 dtype。
- 只接受失败结果和非空 `uint8` 图像；processed 必须是 `H×W`，raw 只允许 `H×W` 或 `H×W×3`。非法 dtype、维数或通道数快速失败且不进入 PNG 编码。
- 第一次不可恢复的 `OSError` 由调用边界记录一次 warning，并把该 store 在当前进程熔断；后续 record 直接返回 `DISABLED`，不再编码、写盘或重复打印 warning。

- [x] **Step 1: 写首次保存、PNG 往返和 metadata schema 测试**

```python
def test_failure_store_writes_complete_bundle(tmp_path: Path) -> None:
    store = OcrFailureStore(tmp_path)
    record = store.record(
        make_invalid_counter_result("99/15"),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet="0123456789/IDSB",
        letter=(140, 113, 99),
        threshold=64,
    )

    assert record.status is OcrFailureRecordStatus.SAVED
    assert record.directory is not None
    assert {path.name for path in record.directory.iterdir()} == {"raw.png", "processed.png", "metadata.json"}
    assert np.array_equal(np.asarray(Image.open(record.directory / "raw.png")), RAW_IMAGE)
```

先单独构造 `OcrFailureStore(tmp_path / "missing")` 并断言 root 仍不存在；只有第一次成功 record 才创建目录。该断言必须直接检查 `Path.exists()`，不能依赖已忽略 `log/` 的 git 状态。

- [x] **Step 2: 写持久去重和四级限额测试**

同 processed/context 但 score、latency、captured_at 不同仍是 `DUPLICATE`；重新构造 store 后仍能识别已有 digest。改变 reason、model、text、area 或 processed bytes 必须产生新 digest。用小值分别验证 `max_total_samples`、`max_samples_per_profile`、`max_total_bytes` 和 `max_new_samples_per_process`，未知目录不得被计数或删除。

- [x] **Step 3: 写非法 profile/图像和原子发布失败测试**

monkeypatch `atomic_replace()` 抛出 `OSError`，断言没有包含 `metadata.json` 的 final 目录且本次 `.tmp` 被清理；第二次 record 直接返回 `DISABLED` 且不再调用编码/写入。另模拟“发布前另一个 store 已创建同 digest final”，验证返回 `DUPLICATE` 且不覆盖已有 bundle。`../escape`、空数组、float 图像、`H×W×1/2/4` raw、三维 processed 和 valid result 都必须在写文件前失败。

- [x] **Step 4: 写 metadata 离线解析重放测试**

读取刚写出的 `metadata.json`，只用其中的 `raw_text`、`score`、`model`、`expected_total` 构造 `RawOcrResult` 并调用 `DigitCounter._parse_result()`；断言重放结果的 `normalized_text`、`valid`、`reason` 和 value 与 metadata 一致。这个测试不调用 fake engine，更不能加载真实模型。

- [x] **Step 5: 运行测试并确认因 store 不存在而失败**

Run: `uv run pytest tests/test_ocr_failure_store.py -q`

- [x] **Step 6: 实现最小同步 store；不加入异步队列、数据库或自动训练集标注**

- [x] **Step 7: 运行定向检查并提交**

Run:

```powershell
uv run pytest tests/test_ocr_failure_store.py -q
uv run ruff check module/ocr/failure_store.py tests/test_ocr_failure_store.py --no-cache
uv run ruff format --check module/ocr/failure_store.py tests/test_ocr_failure_store.py
uv run ty check module/ocr/failure_store.py
git diff --check
```

Commit: `feat: 建立OCR失败样本存储`

---

### Task 4: 让结构化数字接口按需记录失败样本

**Files:**
- Modify: `module/ocr/ocr.py`
- Modify: `tests/test_ocr_result.py`
- Modify: `tests/test_ocr_failure_store.py`

**Interfaces:**

```python
def recognize(
    self,
    image,
    direct_ocr=False,
    *,
    failure_store: OcrFailureRecorder | None = None,
) -> RecognitionResult[...]: ...
```

`Digit`、`DigitCounter`、`Duration` 的新接口都接受可选 recorder。解析失败且 recorder 非 `None` 时，使用同一次推理已经保留的 raw/processed ROI 调用 `record()`；成功结果绝不写盘。`_record_failure()` 必须把允许 list 的 `self.letter` 规范化为恰好三个 `int` 的 tuple，并把 Counter 的 `expected_total` 原样传入 recorder，离线解析才能复现同一业务约束。

具体 store 第一次不可恢复的 `OSError` 会先熔断自身并向外抛出；OCR 调用边界捕获它，只记录一次不含 OCR 原文的 warning，不能把诊断失败升级成业务失败，结果对象仍原样返回。后续 store 返回 `DISABLED`，调用边界不再 warning。参数校验类 `ValueError` 不吞掉，因为它表示 profile、letter 或调用契约错误。

- [x] **Step 1: 写 invalid 保存、valid 不保存、重复 invalid 去重测试**

- [x] **Step 2: 写 store 抛 `OSError` 但结构化结果仍返回的测试**

```python
def test_recording_error_does_not_change_recognition_result() -> None:
    store = FailingStore(OSError("disk full"))

    result = make_counter("99/15").recognize(TEST_IMAGE, failure_store=store)

    assert result.reason is RecognitionFailureReason.CURRENT_EXCEEDS_TOTAL
```

继续调用同一个 store，断言第二次仍返回结构化失败，但编码/写入 fake 没有再次被调用，warning 也只有一条；另用 `letter=[140, 113, 99]` 验证 recorder 实际收到 `(140, 113, 99)`。

- [x] **Step 3: 运行测试并确认因 recognize 尚未连接 store 而失败**

Run: `uv run pytest tests/test_ocr_result.py tests/test_ocr_failure_store.py -q`

- [x] **Step 4: 实现一个受保护 `_record_failure()`，三个解析器复用该边界**

不得让 `RecognitionResult` 持有 NumPy 数组，不得让 `Ocr` 反向依赖 config 或 device；是否启用 store 由业务调用方决定。

- [x] **Step 5: 运行定向检查并提交**

Run:

```powershell
uv run pytest tests/test_ocr_result.py tests/test_ocr_failure_store.py tests/test_ocr_options.py -q
uv run ruff check module/ocr tests/test_ocr_result.py tests/test_ocr_failure_store.py --no-cache
uv run ruff format --check module/ocr tests/test_ocr_result.py tests/test_ocr_failure_store.py
uv run ty check module/ocr
git diff --check
```

Commit: `feat: 记录结构化OCR失败样本`

---

### Task 5: 跑通 `meow_get_buy_count()` 第一条纵向切片

**Files:**
- Modify: `module/meowfficer/buy.py`
- Create: `tests/test_meowfficer_buy.py`

`module/meowfficer/buy.py` 额外从 `module.exception` 导入 `ScriptError`，用于防御固定单 ROI 的金币 OCR 意外返回列表。

**Behavior:**

```python
failure_store = OCR_FAILURE_STORE if self.config.Error_SaveError else None
counter_result = MEOWFFICER.recognize(
    self.device.image,
    expected_total=BUY_MAX,
    failure_store=failure_store,
)
if not counter_result.valid or counter_result.value is None:
    continue

remain, bought, total = counter_result.value
coins_result = MEOWFFICER_COINS.recognize(self.device.image, failure_store=failure_store)
if isinstance(coins_result, list):
    raise ScriptError("MEOWFFICER_COINS 必须使用单个 OCR 区域")
if not coins_result.valid or coins_result.value is None:
    continue

coins = coins_result.value
break
```

约束：

- Counter 无效或 total 不是 `BUY_MAX` 时不运行金币 OCR；这删除每个失败帧一次确定无用推理。`0/0`、`14/14` 等结构合法但不符合本页面业务约束的结果统一成为 `UNEXPECTED_TOTAL`，由同一次 recognize 保存失败样本。
- Counter 成功而金币失败时仍使用现有循环截下一帧重试，不能把失败解释为 0 金币。
- `0/15` 是合法 Counter；合法数字 `0` 也能作为金币值，不得用真假判断 value。
- 超时/有限测试循环全部失败时仍记录原 warning 并返回 0。
- 迁移后的调用点删除 `total != BUY_MAX` 的静默修正分支，改为识别失败并重试；`_meow_get_buy_count()` 的购买计算保持不变。
- 不修改 ReplayDevice；P0 测试用有限帧 generator 与 fake structured OCR 锁定重试顺序，真实业务 Replay 仍属于 P2。

`tests/test_meowfficer_buy.py` 明确定义有限 fake，不构造真实 config/device，也不等待真实 Timer：

```python
class SequenceOcr:
    def __init__(self, results: list[RecognitionResult[object]]) -> None:
        self._results = iter(results)
        self.calls: list[dict[str, object]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def recognize(
        self,
        image: np.ndarray,
        direct_ocr: bool = False,
        *,
        expected_total: int | None = None,
        failure_store: object | None = None,
    ) -> RecognitionResult[object]:
        del image, direct_ocr
        self.calls.append({"expected_total": expected_total, "failure_store": failure_store})
        return next(self._results)


class _TestBuyer:
    _meow_get_buy_count = staticmethod(MeowfficerBuy._meow_get_buy_count)

    def __init__(self, frames: list[np.ndarray], *, save_error: bool) -> None:
        self._frames = frames
        self.device = SimpleNamespace(image=frames[0])
        self.config = SimpleNamespace(Error_SaveError=save_error)

    def loop(self, skip_first=True, timeout=None):
        del skip_first, timeout
        for frame in self._frames:
            self.device.image = frame
            yield frame

    def meow_get_buy_count(self, buy_amount: int, overflow_th: int) -> int:
        buyer = cast("MeowfficerBuy", self)
        return MeowfficerBuy.meow_get_buy_count(buyer, buy_amount, overflow_th)


def make_buyer_with_frames(count: int, *, save_error: bool) -> _TestBuyer:
    frames = [np.full((2, 2, 3), index, dtype=np.uint8) for index in range(count)]
    return _TestBuyer(frames, save_error=save_error)
```

同文件定义 `valid_counter()`、`invalid_counter()`、`valid_digit()`、`invalid_digit()`，全部直接构造满足 DTO 不变量的 `RecognitionResult[object]`，固定 `latency_seconds=0.0`、profile 和 model；不要用 MagicMock 隐藏调用签名。`SequenceOcr` 为 Counter 记录 `expected_total`，金币调用应记录 `None`。

- [x] **Step 1: 写“无效计数器 → 下一帧成功”的调用顺序测试**

```python
def test_buy_count_retries_counter_before_reading_coins(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = SequenceOcr([invalid_counter("loading"), valid_counter((15, 0, 15))])
    coins = SequenceOcr([valid_digit(1500)])
    buyer = make_buyer_with_frames(2, save_error=True)
    monkeypatch.setattr(buy_module, "MEOWFFICER", counter)
    monkeypatch.setattr(buy_module, "MEOWFFICER_COINS", coins)

    assert buyer.meow_get_buy_count(buy_amount=1, overflow_th=-1) == 1
    assert counter.call_count == 2
    assert coins.call_count == 1
```

- [x] **Step 2: 写合法零、业务 total 失败、金币失败重试、全部失败和 SaveError 关闭测试**

明确断言传给 Counter fake 的 `expected_total` 始终为 15，`0/0` 返回 `UNEXPECTED_TOTAL` 并且金币 fake 不被调用；断言传给两个 fake OCR 的 `failure_store`：`Error_SaveError=True` 时是模块默认 store，False 时为 `None`。连续失败测试使用有限 generator 进入 `for ... else`，不能等待真实两秒。

- [x] **Step 3: 运行测试并确认当前代码仍调用旧 `.ocr()` 且失败帧也识别金币**

Run: `uv run pytest tests/test_meowfficer_buy.py -q`

- [x] **Step 4: 迁移唯一业务调用点并保持购买计算不变**

- [x] **Step 5: 运行指挥喵与 OCR 定向测试**

Run:

```powershell
uv run pytest tests/test_meowfficer_buy.py tests/test_meowfficer.py tests/test_meowfficer_base.py tests/test_meowfficer_collect.py tests/test_ocr_result.py tests/test_ocr_failure_store.py tests/test_ocr_options.py -q
uv run ruff check module/meowfficer/buy.py tests/test_meowfficer_buy.py --no-cache
uv run ruff format --check module/meowfficer/buy.py tests/test_meowfficer_buy.py
uv run ty check module/meowfficer/buy.py
git diff --check
```

- [x] **Step 6: 提交**

Commit: `fix: 收紧指挥喵购买状态识别`

---

### Task 6: 更新路线图状态并完成全量门禁

**Files:**
- Modify: `docs/next-generation-framework-and-ocr-roadmap.md`
- Modify: `docs/superpowers/plans/2026-07-11-cnocr-structured-results-p0.md`（只勾选实际完成项）

- [x] **Step 1: 在路线图 P0 下补实施状态和真实文件链接**

只记录已经完成的结果契约、失败 bundle 和 meow 纵向切片；Duration 虽有结构化解析但尚未迁移生产调用点时必须明确写“接口已具备，调用点待按触碰迁移”。P1～P5 状态不变。

- [x] **Step 2: 运行依赖、格式、类型、测试和差异全门禁**

Run:

```powershell
uv sync --check
uv run ruff check . --no-cache
uv run ruff format --check .
uv run ty check
uv run pytest
git diff --check
git status --short
```

Expected: 所有命令退出码为 0；pytest 无新增失败；`git status --short` 只包含本计划列出的文件，没有模型文件或真实截图。由于整个 `log/` 已被忽略，不能用 git status 证明默认失败目录未被测试创建；该性质由 Task 3 的 `Path.exists()` 测试锁定。

- [x] **Step 3: 运行一次严格代码审查**

审查重点：旧 `.ocr()` 是否真未外溢严格语义、失败样本是否可能越权采集一般文本、摘要是否稳定、临时目录失败是否清理、合法 0 是否被真假判断误伤、meow 失败帧是否确实少一次金币推理。

- [x] **Step 4: 修复审查发现后重新运行全门禁**

- [x] **Step 5: 提交文档状态**

Commit: `docs: 记录OCR结构化结果落地状态`

---

### Task 7: 在 fork 上创建或更新本分支的 draft PR

**Files:**
- No source changes expected.

- [ ] **Step 1: 核对当前分支、工作区、origin 和 GitHub 身份**

Run:

```powershell
git branch --show-current
git status --short
git remote -v
gh auth status
gh pr list --repo NothingToDooo/AzurLaneAutoScript --head docs/next-generation-ocr-roadmap --json number,url,state,isDraft,headRefName,baseRefName
```

Expected: 分支仍为 `docs/next-generation-ocr-roadmap`；工作区干净；origin 是 `NothingToDooo/AzurLaneAutoScript`；活动账号为 `NothingToDooo`。计划编写时 live 查询该 head 返回空列表，因此不能假定已有 PR；执行时若仍为空则创建一个 draft，若已经存在则只更新该 PR，绝不创建第二个。

- [ ] **Step 2: 推送当前分支并验证 PR 已包含 P0 提交**

Run:

Run: `git push origin docs/next-generation-ocr-roadmap`

若 head 查询仍为空，使用 GitHub 发布流程创建：base=`NothingToDooo/AzurLaneAutoScript:master`、head=`NothingToDooo:docs/next-generation-ocr-roadmap`、draft=true、标题=`OCR 结构化结果与下一代路线图`。PR 正文必须概括：CnOCR 模型保持不变、结构化结果与严格解析、受控失败样本、meow 首切片、验证命令，以及 P1～P5 未进入本批。

随后按返回的 PR URL 运行：`gh pr view <PR-URL> --json number,url,state,isDraft,headRefOid,commits,statusCheckRollup`

- [ ] **Step 3: 若已有检查，等待结束并读取失败日志；检查通过前不宣称完成**

新建时保持 draft；复用时保持 PR 的现有 draft/ready 状态。不擅自 merge，不切换默认分支，不修改其他远端分支。

---

## P0 Exit Checklist

- [x] CnOCR 原始 text 与 score 在第三方边界被严格保留。
- [x] 新 Digit/Counter/Duration 结构化结果能区分合法 0 与失败。
- [x] 新 Counter 拒绝部分匹配和 `99/15`，新 Duration 拒绝非法分钟/秒。
- [x] 旧 `.ocr()` 返回与未迁移调用点保持兼容。
- [x] 失败 bundle 含 raw、processed、metadata，按稳定摘要去重并受容量限制。
- [x] 只有显式 store + `Error_SaveError` 才落盘，一般文本 OCR 不自动采集。
- [x] 指挥喵 Counter 失败时不再执行金币 OCR，下一帧恢复和金币失败均可重试。
- [x] P1～P5、模型替换和 ReplayDevice 未混入本批代码。
- [ ] 全量门禁通过，fork 上本分支的 draft PR 已创建或更新，检查状态已核实。
