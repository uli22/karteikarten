s1 = "3470 Gb 1670 - 1633-1670 - F102779701"
s2 = "3470 Gb 1670 - 1633-1670 - F102779701"

print("=== Laengenvergleich ===")
print(f"Laenge s1: {len(s1)} Zeichen")
print(f"Laenge s2: {len(s2)} Zeichen")

print()
print("=== Identitaet ===")
print(f"s1 == s2: {s1 == s2}")

print()
print("=== Bytes ===")
b1 = s1.encode("utf-8")
b2 = s2.encode("utf-8")
print(f"s1 bytes ({len(b1)}): {b1.hex()}")
print(f"s2 bytes ({len(b2)}): {b2.hex()}")
print(f"Bytes identisch: {b1 == b2}")

print()
print("=== Zeichen-fuer-Zeichen (Code Points) ===")
print("s1:", " ".join(f"U+{ord(c):04X}({c!r})" for c in s1))
print("s2:", " ".join(f"U+{ord(c):04X}({c!r})" for c in s2))

print()
print("=== Auf unsichtbare Zeichen pruefen ===")
for label, s in [("s1", s1), ("s2", s2)]:
    for i, c in enumerate(s):
        cp = ord(c)
        is_hidden = (
            cp <= 0x20
            or (0x200B <= cp <= 0x200F)
            or (0x2028 <= cp <= 0x2029)
            or (0xFE00 <= cp <= 0xFE0F)
            or (0x2060 <= cp <= 0x2064)
            or c in "\u00A0\u1680\u180E\u205F\u3000\uFEFF\u00AD\u2060"
        )
        if is_hidden and c not in " \t\n\r":
            print(f"  {label}[{i}] U+{cp:04X} {c!r} <-- UNSICHTBAR/STEUERZEICHEN!")

print()
print("=== repr() ===")
print(f"s1: {s1!r}")
print(f"s2: {s2!r}")

print()
print("=== diff: Unterschiedliche Positionen ===")
for i, (c1, c2) in enumerate(zip(s1, s2)):
    if c1 != c2:
        print(f"  Position {i}: s1={c1!r} U+{ord(c1):04X} vs s2={c2!r} U+{ord(c2):04X}")
if len(s1) != len(s2):
    print(f"  Laengen unterschiedlich!")
