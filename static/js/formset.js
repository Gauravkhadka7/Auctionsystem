/**
 * Generic "Add another row" handler for Django inline formsets.
 * Usage: <button data-formset-add="specs">Add specification</button>
 * with the formset's rows sharing a container: <div data-formset-container="specs">
 * and an empty-form template: <template data-formset-empty="specs">...</template>
 */
(function () {
  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-formset-add]");
    if (!btn) return;
    const key = btn.dataset.formsetAdd;
    const container = document.querySelector(`[data-formset-container="${key}"]`);
    const template = document.querySelector(`[data-formset-empty="${key}"]`);
    const totalInput = document.querySelector(`#id_${key}-TOTAL_FORMS`);
    if (!container || !template || !totalInput) return;

    const index = parseInt(totalInput.value, 10);
    const html = template.innerHTML.replace(/__prefix__/g, index);
    const wrapper = document.createElement("div");
    wrapper.innerHTML = html;
    container.appendChild(wrapper);
    totalInput.value = index + 1;
  });

  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-formset-remove]");
    if (!btn) return;
    e.preventDefault();
    const row = btn.closest("[data-formset-row]");
    const deleteInput = row ? row.querySelector('input[type="checkbox"][name$="-DELETE"]') : null;
    if (deleteInput) {
      deleteInput.checked = true;
      row.style.display = "none";
    } else if (row) {
      row.remove();
    }
  });
})();
