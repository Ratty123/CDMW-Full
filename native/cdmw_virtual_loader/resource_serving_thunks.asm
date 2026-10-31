; Package-worker slots for served resources. Each thunk tail-jumps to the slot it serves
; or forwards to, so every register and stack argument reaches it unchanged: the game's
; loads take a status pointer as their fifth argument. resource_serving.cpp decides and
; fills the targets; nothing here allocates or locks.

EXTERN cdmw_serve_load:PROC
EXTERN cdmw_serve_async:PROC
EXTERN cdmw_serve_exists:PROC
EXTERN cdmw_serve_size:PROC
EXTERN cdmw_stand_in:BYTE
EXTERN cdmw_next_load:QWORD
EXTERN cdmw_loose_load:QWORD
EXTERN cdmw_next_async:QWORD
EXTERN cdmw_loose_async:QWORD
EXTERN cdmw_next_exists:QWORD
EXTERN cdmw_next_size:QWORD
EXTERN cdmw_next_request:QWORD
EXTERN cdmw_loose_request:QWORD

.code

; Keeps the four argument registers in the caller's home space around a decision call
; on `source`, then restores them.
DECIDE MACRO helper, source
    mov [rsp+8], rcx
    mov [rsp+10h], rdx
    mov [rsp+18h], r8
    mov [rsp+20h], r9
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    mov rcx, source
    call helper
    add rsp, 28h
    mov rcx, [rsp+8]
    mov rdx, [rsp+10h]
    mov r8, [rsp+18h]
    mov r9, [rsp+20h]
ENDM

; Load (slot 2) and async load (slot 13): (worker, context, request, mode, status...).
cdmw_thunk_load PROC FRAME
    DECIDE cdmw_serve_load, r8
    test eax, eax
    jz forward
    lea rcx, cdmw_stand_in
    jmp qword ptr [cdmw_loose_load]
forward:
    jmp qword ptr [cdmw_next_load]
cdmw_thunk_load ENDP

cdmw_thunk_async PROC FRAME
    DECIDE cdmw_serve_async, r8
    test eax, eax
    jz forward
    lea rcx, cdmw_stand_in
    jmp qword ptr [cdmw_loose_async]
forward:
    jmp qword ptr [cdmw_next_async]
cdmw_thunk_async ENDP

; Exists (slot 10): (worker, path).
cdmw_thunk_exists PROC FRAME
    DECIDE cdmw_serve_exists, rdx
    test eax, eax
    jz forward
    mov eax, 1
    ret
forward:
    jmp qword ptr [cdmw_next_exists]
cdmw_thunk_exists ENDP

; Size (slot 11): (worker, path, size out). cdmw_serve_size writes the size when served.
cdmw_thunk_size PROC FRAME
    mov [rsp+8], rcx
    mov [rsp+10h], rdx
    mov [rsp+18h], r8
    mov [rsp+20h], r9
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    mov rcx, rdx
    mov rdx, r8
    call cdmw_serve_size
    add rsp, 28h
    mov rcx, [rsp+8]
    mov rdx, [rsp+10h]
    mov r8, [rsp+18h]
    mov r9, [rsp+20h]
    test eax, eax
    jz forward
    mov eax, 1
    ret
forward:
    jmp qword ptr [cdmw_next_size]
cdmw_thunk_size ENDP

; Slots acting on a load in progress: (worker, request, ...). A request the stand-in
; started (its owner at +0x20) goes back to the loose-file worker.
FOLLOW MACRO slot
cdmw_thunk_request&slot PROC
    test rdx, rdx
    jz forward&slot
    lea rax, cdmw_stand_in
    cmp [rdx+20h], rax
    jne forward&slot
    mov rcx, rax
    jmp qword ptr [cdmw_loose_request + slot*8]
forward&slot:
    jmp qword ptr [cdmw_next_request + slot*8]
cdmw_thunk_request&slot ENDP
ENDM

FOLLOW 3
FOLLOW 4
FOLLOW 5
FOLLOW 6
FOLLOW 12

END
