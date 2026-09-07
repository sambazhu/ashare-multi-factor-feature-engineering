import re
import json

with open('/data1/wkzq/ashare/index.html.bak_20260901_213024', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Add xlsx.full.min.js in head
if 'vendor/xlsx.full.min.js' not in html:
    html = html.replace('</head>', '<script src="vendor/xlsx.full.min.js"></script>\n</head>', 1)

# 2. Add 90d span button and set 90d default in HTML
old_span_buttons = '''      <button id="btn-span-10" onclick="setCalendarSpan(10)" class="px-2 py-0.5 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 font-semibold hover:bg-slate-200 transition">10天</button>
      <button id="btn-span-15" onclick="setCalendarSpan(15)" class="px-2 py-0.5 rounded border border-blue-500/60 bg-blue-500/10 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300 font-bold hover:bg-blue-500/20 transition">15天</button>
      <button id="btn-span-30" onclick="setCalendarSpan(30)" class="px-2 py-0.5 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 font-semibold hover:bg-slate-200 transition">30天</button>
      <button id="btn-span-60" onclick="setCalendarSpan(60)" class="px-2 py-0.5 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 font-semibold hover:bg-slate-200 transition">60天</button>'''

new_span_buttons = '''      <button id="btn-span-10" onclick="setCalendarSpan(10)" class="px-2 py-0.5 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 font-semibold hover:bg-slate-200 transition">10天</button>
      <button id="btn-span-15" onclick="setCalendarSpan(15)" class="px-2 py-0.5 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 font-semibold hover:bg-slate-200 transition">15天</button>
      <button id="btn-span-30" onclick="setCalendarSpan(30)" class="px-2 py-0.5 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 font-semibold hover:bg-slate-200 transition">30天</button>
      <button id="btn-span-60" onclick="setCalendarSpan(60)" class="px-2 py-0.5 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 font-semibold hover:bg-slate-200 transition">60天</button>
      <button id="btn-span-90" onclick="setCalendarSpan(90)" class="px-2 py-0.5 rounded border border-blue-500/60 bg-blue-500/10 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300 font-bold hover:bg-blue-500/20 transition shadow-sm">90天(默认)</button>'''

html = html.replace(old_span_buttons, new_span_buttons)

# 3. Add Custom Industry Toolbar
custom_toolbar_html = '''  <!-- Custom Industry Group Toolbar -->
  <div class="bg-indigo-50/50 dark:bg-[#0c121e] border-b border-slate-200 dark:border-slate-800/80 px-4 py-1.5 flex flex-wrap items-center justify-between gap-2 shrink-0">
    <div class="flex items-center gap-1.5 overflow-x-auto" id="custom-group-tabs-container">
      <span class="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center gap-1 shrink-0 mr-1">
        <i data-lucide="layers" class="w-3.5 h-3.5 text-indigo-600"></i> 产业大类:
      </span>
      <button id="tab-cgrp-all" onclick="selectCustomGroupTab('all')" class="px-2.5 py-0.5 rounded-md border border-indigo-500/60 bg-indigo-600 text-white font-bold text-xs shadow-sm transition">
        全部大类
      </button>
      <!-- Dynamic group tabs inserted by JS -->
    </div>
    <div class="flex items-center gap-2">
      <button onclick="openCustomIndustryModal()" class="flex items-center gap-1.5 bg-white dark:bg-slate-800 hover:bg-indigo-50 dark:hover:bg-slate-700 text-indigo-700 dark:text-indigo-300 px-2.5 py-1 rounded-lg border border-indigo-200 dark:border-slate-700 font-bold text-xs transition shadow-sm">
        <i data-lucide="folder-cog" class="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400"></i>
        <span>自定义行业分类 & Excel 导入导出</span>
      </button>
    </div>
  </div>
'''

html = html.replace('  <!-- Strategy Factor Toolbar -->', custom_toolbar_html + '\n  <!-- Strategy Factor Toolbar -->')

# 4. Add Custom Category select to industry filter bar
old_sw_filter = '''      <!-- ShenWan Level 1 -->
      <div class="flex items-center gap-1 text-slate-600 dark:text-slate-400 font-medium">
        <span>申万1级:</span>
        <select id="select-sw-ind1" onchange="onSw1Change()" class="bg-white dark:bg-[#121927] border border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-xs rounded-lg py-1 px-1.5 max-w-[100px]">
          <option value="all">全1级</option>
        </select>
      </div>'''

new_sw_filter = '''      <!-- Custom Group Cascading Select -->
      <div class="flex items-center gap-1 text-slate-600 dark:text-slate-400 font-medium">
        <span class="text-indigo-600 dark:text-indigo-400 font-bold">产业大类:</span>
        <select id="select-custom-group" onchange="onCustomGroupChange()" class="bg-white dark:bg-[#121927] border border-indigo-300 dark:border-indigo-700 text-indigo-900 dark:text-indigo-200 font-bold text-xs rounded-lg py-1 px-1.5 max-w-[110px]">
          <option value="all">全产业大类</option>
        </select>
      </div>

      <!-- ShenWan Level 1 -->
      <div class="flex items-center gap-1 text-slate-600 dark:text-slate-400 font-medium">
        <span>申万1级:</span>
        <select id="select-sw-ind1" onchange="onSw1Change()" class="bg-white dark:bg-[#121927] border border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-xs rounded-lg py-1 px-1.5 max-w-[100px]">
          <option value="all">全1级</option>
        </select>
      </div>'''

html = html.replace(old_sw_filter, new_sw_filter)

# 5. Add Custom Industry Modal markup before K-line Modal
custom_modal_html = '''  <!-- Modal 0: Custom Industry Management & Excel Import/Export -->
  <div id="custom-industry-modal" class="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm hidden flex items-center justify-center p-4">
    <div class="bg-white dark:bg-[#0f172a] border border-slate-300 dark:border-slate-700 rounded-xl w-full max-w-4xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden">
      <!-- Header -->
      <div class="bg-gradient-to-r from-indigo-900 via-blue-900 to-slate-900 px-5 py-3 text-white flex justify-between items-center shrink-0">
        <div class="flex items-center gap-2">
          <i data-lucide="layers" class="w-4 h-4 text-amber-300"></i>
          <h3 class="text-sm font-bold">自定义产业大类体系管理与 Excel 导入导出</h3>
        </div>
        <button onclick="closeModal('custom-industry-modal')" class="text-slate-400 hover:text-white transition">
          <i data-lucide="x" class="w-5 h-5"></i>
        </button>
      </div>
      
      <!-- Content -->
      <div class="p-4 overflow-y-auto space-y-4 flex-grow text-xs">
        <div class="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg p-3 text-slate-700 dark:text-slate-300 space-y-1">
          <div class="font-bold text-blue-900 dark:text-blue-300 flex items-center gap-1.5">
            <i data-lucide="info" class="w-4 h-4 text-blue-600"></i> 易用性操作指南
          </div>
          <p class="text-[11px] leading-relaxed">
            支持将 31 个申万一级行业灵活划分为宏观产业大类（如科技创造、民生消费、资源保障等）。您可以在下方直接下拉调整，也可以点击“下载标准 Excel 模板”在本地编辑后一键上传导入，修改后永久保存在浏览器本地并实时生效！
          </p>
        </div>

        <!-- Actions Toolbar -->
        <div class="flex flex-wrap items-center justify-between gap-2 p-2.5 bg-slate-100 dark:bg-slate-800/60 rounded-lg border border-slate-200 dark:border-slate-700">
          <div class="flex items-center gap-2">
            <button onclick="downloadExcelTemplate()" class="flex items-center gap-1.5 bg-white dark:bg-slate-700 hover:bg-slate-100 dark:hover:bg-slate-600 text-slate-800 dark:text-slate-100 px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 font-bold transition shadow-sm">
              <i data-lucide="download" class="w-3.5 h-3.5 text-blue-600"></i>
              <span>下载标准 Excel 模板</span>
            </button>

            <label class="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded-lg font-bold cursor-pointer transition shadow-sm">
              <i data-lucide="upload" class="w-3.5 h-3.5"></i>
              <span>导入 Excel 映射表</span>
              <input type="file" id="excel-file-input" accept=".xlsx, .xls, .csv" class="hidden" onchange="handleExcelImport(event)" />
            </label>

            <button onclick="exportCustomIndustryExcel()" class="flex items-center gap-1.5 bg-white dark:bg-slate-700 hover:bg-slate-100 dark:hover:bg-slate-600 text-slate-800 dark:text-slate-100 px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 font-bold transition shadow-sm">
              <i data-lucide="file-spreadsheet" class="w-3.5 h-3.5 text-emerald-600"></i>
              <span>导出当前分类 Excel</span>
            </button>
          </div>

          <div class="flex items-center gap-2">
            <button onclick="resetCustomGroupsToDefault()" class="text-amber-700 dark:text-amber-400 hover:underline font-semibold flex items-center gap-1 text-xs">
              <i data-lucide="rotate-ccw" class="w-3 h-3"></i> 恢复系统默认
            </button>
          </div>
        </div>

        <!-- Interactive Mapping Grid -->
        <div class="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
          <table class="w-full text-left border-collapse">
            <thead class="bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-bold border-b border-slate-200 dark:border-slate-700">
              <tr>
                <th class="py-2 px-3 w-12 text-center">#</th>
                <th class="py-2 px-3 w-44">申万一级行业 (31个)</th>
                <th class="py-2 px-3 w-48">所属产业大类</th>
                <th class="py-2 px-3">快速切换归属大类</th>
              </tr>
            </thead>
            <tbody id="custom-ind-table-body" class="divide-y divide-slate-200 dark:divide-slate-800">
              <!-- Rendered by JS -->
            </tbody>
          </table>
        </div>
      </div>

      <!-- Footer -->
      <div class="bg-slate-50 dark:bg-[#0b1019] px-5 py-3 border-t border-slate-200 dark:border-slate-800 flex justify-between items-center shrink-0">
        <span id="custom-group-status-msg" class="text-xs text-slate-500 font-medium"></span>
        <div class="flex items-center gap-2">
          <button onclick="closeModal('custom-industry-modal')" class="px-4 py-1.5 rounded-lg bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-bold hover:bg-slate-300 transition">
            取消
          </button>
          <button onclick="saveAndApplyCustomGroups()" class="px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-bold transition shadow-sm flex items-center gap-1">
            <i data-lucide="check" class="w-4 h-4"></i> 保存并立即生效
          </button>
        </div>
      </div>
    </div>
  </div>
'''

html = html.replace('  <!-- Modal 1: 9 Factors Strategy Detail Popover -->', custom_modal_html + '\n  <!-- Modal 1: 9 Factors Strategy Detail Popover -->')

with open('/data1/wkzq/ashare/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print('Updated index.html HTML markup successfully!')
