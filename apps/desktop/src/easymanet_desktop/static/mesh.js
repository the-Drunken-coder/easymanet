// Mesh discovery presentation helpers for the EasyMANET desktop UI.
(function () {
  function emptyMeshMarkup(title, meta) {
    return `
      <div class="empty-state slim">
        <p class="empty-title">${title}</p>
        <p class="empty-meta">${meta}</p>
      </div>
    `;
  }

  window.EMMesh = {
    emptyMeshMarkup,
  };
})();
