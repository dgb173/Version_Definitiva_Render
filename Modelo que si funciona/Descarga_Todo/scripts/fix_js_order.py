import re

# Leer el archivo original
with open('C:\\Users\\Usuario\\Desktop\\v2\\v2\\templates\\index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Definir la sección problemática y la corregida
old_section = '''                    sections.push('<h5 class="mb-3">Vista previa r&aacute;pida</h5>');

                    const recentForm = data.recent_form || {};
                    const homeRecent = recentForm.home || {};
                    const awayRecent = recentForm.away || {};
                    const homeRecord = getRecordPieces(homeRecent);
                    const awayRecord = getRecordPieces(awayRecent);
                    const h2hStats = data.h2h_stats || {};
                    const totalRecent = Math.max(homeRecord.total, awayRecord.total, 0);
                    const getRecordPieces = (teamStats) => {
                        const stats = teamStats || {};
                        const wins = stats.wins ?? 0;
                        const draws = stats.draws ?? 0;
                        const total = stats.total ?? 0;
                        let losses = stats.losses ?? (total - wins - draws);
                        if (losses < 0 || Number.isNaN(losses)) {
                            losses = 0;
                        }
                        return { wins, draws, losses, total };
                    };'''

new_section = '''                    const getRecordPieces = (teamStats) => {
                        const stats = teamStats || {};
                        const wins = stats.wins ?? 0;
                        const draws = stats.draws ?? 0;
                        const total = stats.total ?? 0;
                        let losses = stats.losses ?? (total - wins - draws);
                        if (losses < 0 || Number.isNaN(losses)) {
                            losses = 0;
                        }
                        return { wins, draws, losses, total };
                    };

                    sections.push('<h5 class="mb-3">Vista previa r&aacute;pida</h5>');

                    const recentForm = data.recent_form || {};
                    const homeRecent = recentForm.home || {};
                    const awayRecent = recentForm.away || {};
                    const homeRecord = getRecordPieces(homeRecent);
                    const awayRecord = getRecordPieces(awayRecent);
                    const h2hStats = data.h2h_stats || {};
                    const totalRecent = Math.max(homeRecord.total, awayRecord.total, 0);'''

# Realizar el reemplazo
content_fixed = content.replace(old_section, new_section)

# Guardar el archivo corregido
with open('C:\\Users\\Usuario\\Desktop\\v2\\v2\\templates\\index.html', 'w', encoding='utf-8') as f:
    f.write(content_fixed)

print("Archivo corregido exitosamente!")