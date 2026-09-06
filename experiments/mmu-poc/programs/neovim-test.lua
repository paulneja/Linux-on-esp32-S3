vim.o.swapfile = false
vim.o.undofile = false
vim.o.shadafile = 'NONE'
vim.o.shell = '/usr/bin/dash'
vim.api.nvim_buf_set_lines(0, 0, -1, false, {'uno', 'dos', 'tres'})
vim.cmd('%s/dos/DOS/')
assert(vim.api.nvim_buf_get_lines(0, 0, -1, false)[2] == 'DOS')
vim.cmd('write! /tmp/nvim-result.txt')
assert(vim.fn.readfile('/tmp/nvim-result.txt')[2] == 'DOS')
print('PASS nvim: edit, substitute, write and read')
local data = vim.json.decode(vim.json.encode({number = 17, text = 'esp32'}))
assert(data.number == 17 and data.text == 'esp32')
print('PASS nvim: embedded Lua and JSON')
local output = vim.fn.system({'/usr/bin/dash', '-c', 'printf child-process'})
assert(vim.v.shell_error == 0, 'system exit=' .. vim.v.shell_error)
assert(output == 'child-process', output)
print('PASS nvim: real child process through libuv')
print('NEOVIM TEST PASS')
