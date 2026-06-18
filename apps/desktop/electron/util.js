function booleanFlag(value) {
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return normalized === "true" || normalized === "1" || normalized === "yes" || normalized === "on";
  }
  return value === true || value === 1;
}

module.exports = { booleanFlag };
