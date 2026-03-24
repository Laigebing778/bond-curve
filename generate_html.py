# -*- coding: utf-8 -*-
"""生成包含数据的独立HTML文件"""
import json
import os

# 读取所有数据文件
data = {}
data_files = [
    'data/2025-01-02.json',
    'data/2026-03-06.json',
    'data/2026-3-13.json',
    'data/2026-3-16.json',
    'data/2026-3-17.json',
    'data/2026-3-18.json',
    'data/2026-3-19.json',
    'data/2026-3-20.json',
    'data/2026-3-23.json',
]

print("加载数据文件...")
for fpath in data_files:
    if os.path.exists(fpath):
        date_key = os.path.basename(fpath).replace('.json', '')
        with open(fpath, 'r', encoding='utf-8') as f:
            data[date_key] = json.load(f)
        print(f"  {date_key}: 普通债{len(data[date_key].get('normal', []))}个, 永续债{len(data[date_key].get('perpetual', []))}个")

print(f"\n共加载 {len(data)} 个日期的数据")

html_template = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>收益率期限结构曲线查询</title>
    <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/element-plus/dist/index.css">
    <script src="https://unpkg.com/element-plus"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Microsoft YaHei', sans-serif; background: #f5f7fa; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 15px; text-align: center; }
        .header h1 { font-size: 22px; margin-bottom: 5px; }
        .header p { opacity: 0.9; font-size: 13px; }
        .container { max-width: 1200px; margin: 0 auto; padding: 15px; }
        .search-box { background: white; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
        .chart-box { background: white; border-radius: 8px; padding: 15px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
        .info-card { background: #f8f9fa; border-radius: 8px; padding: 12px; margin-top: 15px; }
        .info-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #eee; }
        .info-label { color: #666; font-size: 13px; }
        .info-value { font-weight: bold; color: #333; font-size: 13px; }
        .positive { color: #67c23a; }
        .negative { color: #f56c6c; }
        .stats { display: flex; gap: 15px; justify-content: center; margin-bottom: 15px; flex-wrap: wrap; }
        .stat-item { text-align: center; padding: 8px 15px; background: #f0f2f5; border-radius: 6px; }
        .stat-value { font-size: 18px; font-weight: bold; color: #667eea; }
        .stat-label { font-size: 11px; color: #999; margin-top: 3px; }
    </style>
</head>
<body>
    <div id="app">
        <div class="header">
            <h1>收益率期限结构曲线查询</h1>
            <p>{{ selectedDate }} | {{ bondType === 'normal' ? '普通债' : '永续债' }} | 直接打开即可使用</p>
        </div>

        <div class="container">
            <div class="stats" v-if="currentData">
                <div class="stat-item">
                    <div class="stat-value">{{ currentData.normal.length }}</div>
                    <div class="stat-label">普通债发行人</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{{ currentData.perpetual.length }}</div>
                    <div class="stat-label">永续债发行人</div>
                </div>
            </div>

            <div class="search-box">
                <el-row :gutter="10" align="middle">
                    <el-col :span="4">
                        <el-select v-model="selectedDate" placeholder="日期" style="width: 100%">
                            <el-option v-for="d in availableDates" :key="d" :label="d" :value="d"></el-option>
                        </el-select>
                    </el-col>
                    <el-col :span="4">
                        <el-radio-group v-model="bondType">
                            <el-radio-button value="normal">普通债</el-radio-button>
                            <el-radio-button value="perpetual">永续债</el-radio-button>
                        </el-radio-group>
                    </el-col>
                    <el-col :span="10">
                        <el-autocomplete v-model="searchText" :fetch-suggestions="querySearch"
                            placeholder="输入发行人名称（如：开封、中铁）" style="width: 100%"
                            @select="onSelectIssuer" :debounce="200" clearable>
                            <template #default="{ item }">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <span style="font-size: 13px;">{{ item.issuer_name }}</span>
                                    <el-tag size="small" type="info">{{ item.bond_count }}只</el-tag>
                                </div>
                            </template>
                        </el-autocomplete>
                    </el-col>
                    <el-col :span="3">
                        <el-button type="primary" @click="loadChartData" :loading="chartLoading" :disabled="!searchText">查询</el-button>
                    </el-col>
                    <el-col :span="3">
                        <el-button @click="clearSearch">清空</el-button>
                    </el-col>
                </el-row>
            </div>

            <div class="chart-box" v-if="chartData">
                <div id="yieldChart" style="width: 100%; height: 420px;"></div>

                <div class="info-card">
                    <el-row :gutter="15">
                        <el-col :span="6">
                            <div class="info-row"><span class="info-label">发行人</span><span class="info-value">{{ chartData.issuer_name }}</span></div>
                            <div class="info-row"><span class="info-label">债券类型</span><span class="info-value">{{ chartData.bond_type }}</span></div>
                        </el-col>
                        <el-col :span="6">
                            <div class="info-row"><span class="info-label">拟合模型</span><span class="info-value">{{ chartData.model_type }}</span></div>
                            <div class="info-row"><span class="info-label">样本数量</span><span class="info-value">{{ chartData.bond_count }}只</span></div>
                        </el-col>
                        <el-col :span="6">
                            <div class="info-row"><span class="info-label">拟合优度R2</span><span class="info-value">{{ (chartData.r_squared * 100).toFixed(1) }}%</span></div>
                            <div class="info-row"><span class="info-label">整体斜率</span>
                                <span class="info-value" :class="chartData.slope_total >= 0 ? 'positive' : 'negative'">{{ chartData.slope_total.toFixed(1) }} bp</span>
                            </div>
                        </el-col>
                        <el-col :span="6">
                            <div class="info-row"><span class="info-label">期限范围</span>
                                <span class="info-value" v-if="chartData.tenor_min">{{ chartData.tenor_min.toFixed(2) }}-{{ chartData.tenor_max.toFixed(2) }}年</span>
                            </div>
                            <div class="info-row"><span class="info-label">曲线形态</span>
                                <span class="info-value" :class="chartData.slope_total >= 0 ? 'positive' : 'negative'">{{ chartData.slope_total >= 0 ? '上行' : '下行' }}</span>
                            </div>
                        </el-col>
                    </el-row>
                </div>

                <div class="info-card" style="margin-top: 12px;">
                    <el-row style="margin-bottom: 8px;">
                        <el-col :span="12"><h4 style="font-size: 14px;">样本债券 ({{ (chartData.bonds || []).length }}只)</h4></el-col>
                        <el-col :span="12" style="text-align: right;">
                            <el-button size="small" type="success" @click="exportExcel">导出CSV</el-button>
                        </el-col>
                    </el-row>
                    <el-table :data="chartData.bonds" stripe size="small" max-height="250" v-if="chartData.bonds && chartData.bonds.length">
                        <el-table-column prop="bond_name" label="债券简称" min-width="140"></el-table-column>
                        <el-table-column prop="bond_code" label="债券代码" width="120"></el-table-column>
                        <el-table-column prop="remain_years" label="期限(年)" width="100" sortable>
                            <template #default="scope">{{ scope.row.remain_years.toFixed(2) }}</template>
                        </el-table-column>
                        <el-table-column prop="ytm" label="收益率(%)" width="100" sortable>
                            <template #default="scope">{{ scope.row.ytm.toFixed(2) }}%</template>
                        </el-table-column>
                    </el-table>
                    <el-empty v-else description="无数据" :image-size="50"></el-empty>
                </div>
            </div>

            <el-empty v-if="!chartData && !chartLoading" description="输入发行人名称查询期限结构曲线" :image-size="100"></el-empty>
        </div>
    </div>

    <script>
    const ALL_DATA = __DATA_PLACEHOLDER__;

    const { createApp, ref, computed, onMounted, nextTick, watch } = Vue;
    const { ElMessage } = ElementPlus;

    createApp({
        setup() {
            const selectedDate = ref('2026-3-20');
            const bondType = ref('normal');
            const availableDates = ref(Object.keys(ALL_DATA));
            const chartData = ref(null);
            const chartLoading = ref(false);
            const searchText = ref('');
            let chart = null;

            const currentData = computed(() => ALL_DATA[selectedDate.value] || { normal: [], perpetual: [] });

            // 切换日期或债券类型时，清空搜索结果
            watch([selectedDate, bondType], () => {
                searchText.value = '';
                chartData.value = null;
                if (chart) {
                    chart.clear();
                    chart = null;
                }
            });

            const querySearch = (queryString, cb) => {
                const list = currentData.value[bondType.value] || [];
                const results = queryString ? list.filter(item => item.issuer_name.includes(queryString)).slice(0, 30) : list.slice(0, 30);
                cb(results);
            };

            const onSelectIssuer = (item) => { searchText.value = item.issuer_name; };

            const clearSearch = () => {
                searchText.value = '';
                chartData.value = null;
                if (chart) {
                    chart.clear();
                    chart = null;
                }
            };

            const loadChartData = async () => {
                if (!searchText.value) { ElMessage.warning('请输入发行人名称'); return; }
                chartLoading.value = true;
                try {
                    const list = currentData.value[bondType.value] || [];
                    const found = list.filter(item => item.issuer_name.includes(searchText.value));
                    if (found.length > 0) {
                        chartData.value = found[0];
                        await nextTick();
                        renderChart();
                    } else {
                        chartData.value = null;
                        ElMessage.warning('未找到该发行人的' + (bondType.value === 'perpetual' ? '永续债' : '普通债') + '数据');
                    }
                } catch (e) {
                    console.error('加载图表失败:', e);
                    ElMessage.error('加载图表失败');
                } finally { chartLoading.value = false; }
            };

            const renderChart = () => {
                try {
                    const chartDom = document.getElementById('yieldChart');
                    if (!chartDom) {
                        console.error('找不到图表容器');
                        return;
                    }
                    if (!chart) chart = echarts.init(chartDom);
                    const bonds = chartData.value.bonds || [];
                    if (bonds.length === 0) {
                        ElMessage.warning('该发行人无债券数据');
                        return;
                    }
                    const sortedBonds = [...bonds].sort((a, b) => a.remain_years - b.remain_years);
                    const scatterData = sortedBonds.map(b => ({ value: [b.remain_years, b.ytm], bond: b }));
                    const xMax = Math.max(...sortedBonds.map(b => b.remain_years));
                    chart.setOption({
                        title: { text: chartData.value.issuer_name, subtext: bondType.value === 'perpetual' ? '永续债期限结构' : '普通债期限结构', left: 'center', textStyle: { fontSize: 14 } },
                        tooltip: { trigger: 'item', formatter: p => '<b>' + p.data.bond.bond_name + '</b><br/>期限: ' + p.data.bond.remain_years.toFixed(2) + '年<br/>收益率: ' + p.data.bond.ytm.toFixed(2) + '%' },
                        grid: { left: '8%', right: '5%', bottom: '12%', top: '18%' },
                        xAxis: { type: 'value', name: '期限(年)', nameLocation: 'middle', nameGap: 25, min: 0, max: Math.max(15, Math.ceil(xMax + 1)) },
                        yAxis: { type: 'value', name: '收益率(%)', nameLocation: 'middle', nameGap: 40 },
                        series: [{ type: 'scatter', data: scatterData, symbolSize: 12, itemStyle: { color: bondType.value === 'perpetual' ? '#e6a23c' : '#5470c6' }, label: { show: true, formatter: p => p.data.bond.bond_name.substring(0, 6), position: 'top', fontSize: 9, color: '#333' } }]
                    }, true);
                } catch (e) {
                    console.error('渲染图表失败:', e);
                    ElMessage.error('渲染图表失败');
                }
            };

            const exportExcel = () => {
                if (!chartData.value || !chartData.value.bonds) return;
                let csv = '债券简称,债券代码,剩余期限(年),收益率(%)\\n';
                chartData.value.bonds.forEach(b => { csv += b.bond_name + ',' + b.bond_code + ',' + b.remain_years + ',' + b.ytm + '\\n'; });
                const blob = new Blob(['\\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = chartData.value.issuer_name + '_' + selectedDate.value + '.csv';
                a.click();
            };

            onMounted(() => { window.addEventListener('resize', () => chart && chart.resize()); });

            return { selectedDate, bondType, availableDates, chartData, chartLoading, searchText, currentData, querySearch, onSelectIssuer, clearSearch, loadChartData, exportExcel };
        }
    }).use(ElementPlus).mount('#app');
    </script>
</body>
</html>'''

# 转换数据为JSON字符串
data_json = json.dumps(data, ensure_ascii=False)

# 替换占位符
html_content = html_template.replace('__DATA_PLACEHOLDER__', data_json)

# 保存文件
output_path = 'data/期限结构曲线查询.html'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html_content)

file_size = os.path.getsize(output_path) / 1024 / 1024
print(f'\n文件已生成: {output_path}')
print(f'文件大小: {file_size:.1f} MB')
print('可直接用浏览器打开，无需服务器！')
print(f'\n包含日期: {", ".join(sorted(data.keys()))}')