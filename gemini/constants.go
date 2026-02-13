package gemini

// Endpoint constants
const (
	EndpointGoogle        = "https://www.google.com"
	EndpointInit          = "https://gemini.google.com/app"
	EndpointGenerate      = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
	EndpointRotateCookies = "https://accounts.google.com/RotateCookies"
	EndpointUpload        = "https://content-push.googleapis.com/upload"
	EndpointBatchExec     = "https://gemini.google.com/_/BardChatUi/data/batchexecute"
)

// GRPC IDs
const (
	GRPCListChats    = "MaZiqc"
	GRPCReadChat     = "hNvQHb"
	GRPCDeleteChat   = "GzXR5e"
	GRPCListGems     = "CNgdBe"
	GRPCCreateGem    = "oMH3Zd"
	GRPCUpdateGem    = "kHv0Vd"
	GRPCDeleteGem    = "UXcSJb"
	GRPCBardActivity = "ESY5D"
)

// Headers
var HeadersGemini = map[string]string{
	"Content-Type":  "application/x-www-form-urlencoded;charset=utf-8",
	"Host":          "gemini.google.com",
	"Origin":        "https://gemini.google.com",
	"Referer":       "https://gemini.google.com/",
	"User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
	"X-Same-Domain": "1",
}

var HeadersRotateCookies = map[string]string{
	"Content-Type": "application/json",
}

var HeadersUpload = map[string]string{
	"Push-ID": "feeds/mcudyrk2a4khkz",
}

// ErrorCode
type ErrorCode int

const (
	ErrorCodeTemporaryError1013   ErrorCode = 1013
	ErrorCodeUsageLimitExceeded   ErrorCode = 1037
	ErrorCodeModelInconsistent    ErrorCode = 1050
	ErrorCodeModelHeaderInvalid   ErrorCode = 1052
	ErrorCodeIPTemporarilyBlocked ErrorCode = 1060
)

// Model represents a Gemini model configuration
type Model struct {
	Name         string
	Header       map[string]string
	AdvancedOnly bool
}

var (
	ModelUnspecified = Model{
		Name:         "unspecified",
		Header:       map[string]string{},
		AdvancedOnly: false,
	}
	ModelG30Pro = Model{
		Name: "gemini-3.0-pro",
		Header: map[string]string{
			"x-goog-ext-525001261-jspb": "[1,null,null,null,\"9d8ca3786ebdfbea\",null,null,0,[4],null,null,1]",
		},
		AdvancedOnly: false,
	}
	ModelG30Flash = Model{
		Name: "gemini-3.0-flash",
		Header: map[string]string{
			"x-goog-ext-525001261-jspb": "[1,null,null,null,\"fbb127bbb056c959\",null,null,0,[4],null,null,1]",
		},
		AdvancedOnly: false,
	}
	ModelG30FlashThinking = Model{
		Name: "gemini-3.0-flash-thinking",
		Header: map[string]string{
			"x-goog-ext-525001261-jspb": "[1,null,null,null,\"5bf011840784117a\",null,null,0,[4],null,null,1]",
		},
		AdvancedOnly: false,
	}
)

var AllModels = []Model{
	ModelUnspecified,
	ModelG30Pro,
	ModelG30Flash,
	ModelG30FlashThinking,
}

func ModelFromName(name string) (Model, bool) {
	for _, m := range AllModels {
		if m.Name == name {
			return m, true
		}
	}
	return ModelUnspecified, false
}
