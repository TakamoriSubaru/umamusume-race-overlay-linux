Tests for hook_race.js against a MOCK IL2CPP runtime (Linux, needs gcc + `pip install frida`).
The mock exports the real il2cpp_* C api with IL2CPP's object layouts, so the script's name resolution, field
reading and hooking run for real. It cannot say anything about the real game's class / field names.

  cd tools/test
  gcc -shared -fPIC -O0 -o /tmp/fr/GameAssembly.dll mock.c      # (mkdir -p /tmp/fr first)
  gcc -O0 -o /tmp/fr/host host.c -ldl && gcc -O0 -o /tmp/fr/host2 host2.c -ldl
  python3 drive.py     # late module + late il2cpp init, discover, configure, string / byte[] scenario, struct array, trace
  python3 drive2.py    # back-to-back races, bogus `this`, garbage pointers, NaN / huge time, List<T>
