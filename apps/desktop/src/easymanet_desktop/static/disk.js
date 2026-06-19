// Disk refresh helpers for the EasyMANET desktop UI.
(function () {
  function diskInventorySignature(diskRecords) {
    return JSON.stringify(
      [...diskRecords]
        .map((disk) => ({
          device: disk.device || "",
          model: disk.model || "",
          mounted: [...(disk.mounted || [])].sort(),
          removable: Boolean(disk.removable),
          size: disk.size_human || "",
          warnings: [...(disk.warnings || [])].sort(),
        }))
        .sort((left, right) => left.device.localeCompare(right.device))
    );
  }

  window.EMDisk = {
    diskInventorySignature,
  };
})();
