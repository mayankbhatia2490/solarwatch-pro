# SolarWatch Pro — Claude Context

## NAS Deployment Path
The app runs on a Synology NAS at:
```
/volume1/docker/solarwatch-pro
```

## Deploy commands (run on NAS via SSH)
```bash
cd /volume1/docker/solarwatch-pro
git pull origin claude/analyze-solar-app-PbdiR
docker compose up -d --build
```

## System
- Location: Karnal, Haryana (29.693°N, 76.999°E)
- System: 3.57 kWp — 6 × Vikram Solar HyperSol N-type bifacial 595W
- Inverter: KSolar 3.4kW single-phase
- Tilt: ~5° (roof pitch), optimal would be 29.7°
- PR: 0.83 assumed (N-type bifacial), bifacial rear gain: 9%
- Utility: UHBVN (Haryana), net metering enabled

## Branch
Active development branch: `claude/analyze-solar-app-PbdiR`
