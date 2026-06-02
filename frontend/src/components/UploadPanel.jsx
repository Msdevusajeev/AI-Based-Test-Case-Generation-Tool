import { useState, useRef, useCallback } from 'react'

const ACCEPTED = ['.pdf', '.docx', '.xlsx']
const ICONS = {
  pdf:  '📄',
  docx: '📝',
  doc:  '📝',
  xlsx: '📊',
  xls:  '📊',
}

const DOC_TYPES = [
  { key: 'srs',        label: 'SRS',        desc: 'Software Requirement Specification (primary)',  required: true },
  { key: 'icd',        label: 'ICD',        desc: 'Interface Control Document',                    required: false },
  { key: 'supporting', label: 'Supporting', desc: 'Additional supporting documents',               required: false },
]

function formatBytes(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

function FileDropZone({ docType, file, loading, error, onFile, onClear }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef()
  const ext = file?.name?.split('.').pop()?.toLowerCase()
  const icon = ICONS[ext] || '📁'

  const onDrop = (e) => {
    e.preventDefault(); setDragging(false)
    onFile(e.dataTransfer.files[0])
  }

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2 mb-2">
        <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${docType.required ? 'bg-amber/20 text-amber border border-amber/30' : 'bg-border text-dim'}`}>
          {docType.label}
        </span>
        <span className="text-xs text-dim">{docType.desc}</span>
        {docType.required && <span className="text-red-400 text-xs">*Mandatory</span>}
      </div>

      <div
        className={`drop-zone rounded-xl p-5 cursor-pointer select-none ${dragging ? 'drag-over' : ''}`}
        onClick={() => inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.xlsx"
          className="hidden"
          onChange={(e) => onFile(e.target.files[0])}
        />

        {loading ? (
          <div className="flex flex-col items-center gap-2">
            <div className="w-6 h-6 border-2 border-amber border-t-transparent rounded-full spin" />
            <p className="text-dim text-xs">Parsing…</p>
          </div>
        ) : file ? (
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-2xl">{icon}</span>
              <div className="text-left">
                <p className="text-text text-sm font-medium">{file.name}</p>
                <p className="text-dim text-xs font-mono">{formatBytes(file.size)}</p>
              </div>
            </div>
            <div className="flex gap-2">
              <span className="text-green-400 text-xs">✓ Uploaded</span>
              <button
                className="text-red-400 text-xs hover:text-red-300"
                onClick={(e) => { e.stopPropagation(); onClear() }}
              >✕ Remove</button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl border border-border flex items-center justify-center text-2xl bg-card flex-shrink-0">📋</div>
            <div className="flex flex-col items-start gap-1">
              <p className="text-dim text-sm">Drop {docType.label} document here or click to browse</p>
              <div className="flex gap-1">
                {ACCEPTED.map(e => (
                  <span key={e} className="px-2 py-0.5 rounded text-xs font-mono bg-border text-dim">{e}</span>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
          ⚠ {error}
        </div>
      )}
    </div>
  )
}

export default function UploadPanel({ onUploaded }) {
  // State for each document type
  const [files, setFiles]     = useState({ srs: null, icd: null, supporting: null })
  const [loading, setLoading] = useState({ srs: false, icd: false, supporting: false })
  const [errors,  setErrors]  = useState({ srs: '', icd: '', supporting: '' })
  const [sessions, setSessions] = useState({ srs: null, icd: null, supporting: null })
  const [preview, setPreview] = useState('')

  const handleFile = useCallback(async (docTypeKey, f) => {
    if (!f) return
    const ext = '.' + f.name.split('.').pop().toLowerCase()
    if (!ACCEPTED.includes(ext)) {
      setErrors(e => ({ ...e, [docTypeKey]: `Unsupported type: ${ext}. Use ${ACCEPTED.join(', ')}` }))
      return
    }
    setErrors(e => ({ ...e, [docTypeKey]: '' }))
    setFiles(fls => ({ ...fls, [docTypeKey]: f }))
    setLoading(ld => ({ ...ld, [docTypeKey]: true }))

    const form = new FormData()
    form.append('file', f)
    form.append('doc_type', docTypeKey)

    try {
      const res = await fetch('/api/upload', { method: 'POST', body: form })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail?.error || 'Upload failed')
      setSessions(s => ({ ...s, [docTypeKey]: data }))
      if (docTypeKey === 'srs') {
        setPreview(data.text_preview)
      }
      // Notify parent with SRS session (primary) and ICD session reference
      const updatedSessions = { ...sessions, [docTypeKey]: data }
      if (updatedSessions.srs) {
        onUploaded({
          ...updatedSessions.srs,
          icd_session_id: updatedSessions.icd?.session_id || null,
          supporting_session_id: updatedSessions.supporting?.session_id || null,
        })
      }
    } catch (e) {
      setErrors(err => ({ ...err, [docTypeKey]: e.message }))
      setFiles(fls => ({ ...fls, [docTypeKey]: null }))
    } finally {
      setLoading(ld => ({ ...ld, [docTypeKey]: false }))
    }
  }, [sessions, onUploaded])

  const handleClear = (docTypeKey) => {
    setFiles(fls => ({ ...fls, [docTypeKey]: null }))
    setSessions(s => ({ ...s, [docTypeKey]: null }))
    setErrors(e => ({ ...e, [docTypeKey]: '' }))
    if (docTypeKey === 'srs') setPreview('')
  }

  return (
    <div className="fade-in">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-7 h-7 rounded bg-amber/10 border border-amber/30 flex items-center justify-center text-amber text-sm font-mono font-bold">1</div>
        <h2 className="text-base font-semibold text-text">Upload Requirements</h2>
        <span className="text-xs text-dim">SRS (required) + ICD + Supporting</span>
      </div>

      {DOC_TYPES.map(dt => (
        <FileDropZone
          key={dt.key}
          docType={dt}
          file={files[dt.key]}
          loading={loading[dt.key]}
          error={errors[dt.key]}
          onFile={(f) => handleFile(dt.key, f)}
          onClear={() => handleClear(dt.key)}
        />
      ))}

      {preview && (
        <div className="mt-2">
          <p className="text-xs text-muted mb-1.5 font-mono uppercase tracking-widest">SRS Preview (first 500 chars)</p>
          <pre className="bg-card border border-border rounded-lg p-3 text-xs text-dim font-mono overflow-auto max-h-32 whitespace-pre-wrap">
            {preview}
          </pre>
        </div>
      )}
    </div>
  )
}
