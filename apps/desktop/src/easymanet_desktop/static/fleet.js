// Fleet and node selection helpers for the EasyMANET desktop UI.
(function () {
  function uniqueNodeNames(nodes) {
    return [...new Set((nodes || []).map((node) => String(node).trim()).filter(Boolean))];
  }

  function roleSshHint(role) {
    if (!role) {
      return "role default";
    }
    return role === "gate" ? "on for gate" : `off for ${role}`;
  }

  window.EMFleet = {
    uniqueNodeNames,
    roleSshHint,
  };
})();
