/** 棋谱库与复盘共用本地SGF导入，文件内容直接发送至本机服务。 */
import { ApiError } from "./api";
import { errText, t } from "./i18n";
import { showScreen, toast } from "./main";

let importing = false;

function updateImportButtons(): void {
  document.querySelectorAll<HTMLButtonElement>("[data-record-import]").forEach((button) => {
    button.disabled = importing;
    button.textContent = t(importing ? "rec.importing" : "rec.import");
  });
}

export function bindRecordImport(button: HTMLButtonElement, input: HTMLInputElement): void {
  updateImportButtons();
  button.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    input.value = ""; // 同一文件失败后可重新选择
    if (!file || importing) return;
    importing = true;
    updateImportButtons();
    try {
      if (file.size > 2 * 1024 * 1024) throw new ApiError("record.too_large", { max_mb: 2 });
      const response = await fetch(`/api/records/import?filename=${encodeURIComponent(file.name)}`, {
        method: "POST", headers: { "Content-Type": "application/x-go-sgf" }, body: file,
      });
      const result = await response.json();
      if (!response.ok) throw new ApiError(result.detail.code, result.detail.args ?? {});
      window.dispatchEvent(new CustomEvent("open-review", { detail: result.file }));
      showScreen("review");
      toast(t("rec.imported"));
    } catch (error) {
      toast(errText(error), true);
    } finally {
      importing = false;
      updateImportButtons();
    }
  });
}
