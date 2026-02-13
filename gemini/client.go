package gemini

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

type GeminiClient struct {
	Client      *http.Client
	AccessToken string
	BuildLabel  string
	SessionID   string
	ReqID       int
	Lock        sync.Mutex
	Cookies     []*http.Cookie
	Proxy       string
}

func NewClient(secure1PSID, secure1PSIDTS string, proxyURL string) (*GeminiClient, error) {
	jar, err := cookiejar.New(nil)
	if err != nil {
		return nil, err
	}

	var transport *http.Transport
	if proxyURL != "" {
		u, err := url.Parse(proxyURL)
		if err != nil {
			return nil, err
		}
		transport = &http.Transport{Proxy: http.ProxyURL(u)}
	} else {
		transport = &http.Transport{}
	}

	client := &http.Client{
		Jar:       jar,
		Transport: transport,
		Timeout:   300 * time.Second,
	}

	cookies := []*http.Cookie{
		{Name: "__Secure-1PSID", Value: secure1PSID, Domain: ".google.com", Path: "/"},
	}
	if secure1PSIDTS != "" {
		cookies = append(cookies, &http.Cookie{Name: "__Secure-1PSIDTS", Value: secure1PSIDTS, Domain: ".google.com", Path: "/"})
	}

	uGoogle, _ := url.Parse("https://google.com")
	uGemini, _ := url.Parse("https://gemini.google.com")
	jar.SetCookies(uGoogle, cookies)
	jar.SetCookies(uGemini, cookies)

	return &GeminiClient{
		Client:  client,
		ReqID:   rand.Intn(90000) + 10000,
		Cookies: cookies,
		Proxy:   proxyURL,
	}, nil
}

func (c *GeminiClient) Init() error {
	c.Lock.Lock()
	defer c.Lock.Unlock()

	snlm0e, bl, sid, err := GetAccessToken(c.Client)
	if err != nil {
		return err
	}
	c.AccessToken = snlm0e
	c.BuildLabel = bl
	c.SessionID = sid
	return nil
}

func (c *GeminiClient) BatchExecute(payloads []RPCData) error {
	c.Lock.Lock()
	reqID := c.ReqID
	c.ReqID += 100000
	c.Lock.Unlock()

	rpcids := make([]string, len(payloads))
	for i, p := range payloads {
		rpcids[i] = p.RPCID
	}

	serializedPayloads := make([][]interface{}, len(payloads))
	for i, p := range payloads {
		serializedPayloads[i] = p.Serialize()
	}

	innerJSON, _ := json.Marshal(serializedPayloads)

	form := url.Values{}
	form.Set("at", c.AccessToken)
	form.Set("f.req", string(innerJSON))

	reqURL, _ := url.Parse(EndpointBatchExec)
	q := reqURL.Query()
	q.Set("rpcids", strings.Join(rpcids, ","))
	q.Set("_reqid", strconv.Itoa(reqID))
	q.Set("rt", "c")
	q.Set("source-path", "/app")
	if c.BuildLabel != "" {
		q.Set("bl", c.BuildLabel)
	}
	if c.SessionID != "" {
		q.Set("f.sid", c.SessionID)
	}
	reqURL.RawQuery = q.Encode()

	req, err := http.NewRequest("POST", reqURL.String(), strings.NewReader(form.Encode()))
	if err != nil {
		return err
	}

	for k, v := range HeadersGemini {
		req.Header.Set(k, v)
	}

	resp, err := c.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return fmt.Errorf("batch execute failed with status: %s", resp.Status)
	}

	if c.Client.Jar != nil {
		u, _ := url.Parse(EndpointGoogle)
		c.Cookies = c.Client.Jar.Cookies(u)
	}

	return nil
}

// Option pattern for optional arguments
type Option func(*generateOptions)

type generateOptions struct {
	Model Model
	Gem   *Gem
	Chat  *ChatSession
	Files []interface{} // string path or []byte or io.Reader
}

func WithModel(m Model) Option {
	return func(o *generateOptions) {
		o.Model = m
	}
}

func WithGem(g *Gem) Option {
	return func(o *generateOptions) {
		o.Gem = g
	}
}

func WithChat(chat *ChatSession) Option {
	return func(o *generateOptions) {
		o.Chat = chat
	}
}

func WithFiles(files []interface{}) Option {
	return func(o *generateOptions) {
		o.Files = files
	}
}

func (c *GeminiClient) GenerateContent(prompt string, opts ...Option) (ModelOutput, error) {
	// Simple wrapper around stream that collects the last output
	var lastOutput ModelOutput
	// We use a channel to collect outputs
	outChan := make(chan ModelOutput)
	errChan := make(chan error)

	go func() {
		defer close(outChan)
		defer close(errChan)
		if err := c.GenerateContentStream(prompt, outChan, opts...); err != nil {
			errChan <- err
		}
	}()

	for out := range outChan {
		lastOutput = out
	}

	select {
	case err := <-errChan:
		return ModelOutput{}, err
	default:
	}

	if len(lastOutput.Candidates) == 0 {
		return ModelOutput{}, fmt.Errorf("no content generated")
	}

	return lastOutput, nil
}

func (c *GeminiClient) GenerateContentStream(prompt string, outChan chan<- ModelOutput, opts ...Option) error {
	options := generateOptions{
		Model: ModelUnspecified,
	}
	for _, o := range opts {
		o(&options)
	}

	if prompt == "" {
		return fmt.Errorf("prompt cannot be empty")
	}

	c.Lock.Lock()
	reqID := c.ReqID
	c.ReqID += 100000
	c.Lock.Unlock()

	var reqFileData []interface{}
	if len(options.Files) > 0 {
		activityPayload := RPCData{
			RPCID:   GRPCBardActivity,
			Payload: "[[[\"bard_activity_enabled\"]]]",
		}
		if err := c.BatchExecute([]RPCData{activityPayload}); err != nil {
			return err
		}

		for _, file := range options.Files {
			filename, err := ParseFileName(file)
			if err != nil {
				return err
			}
			urlStr, err := UploadFile(c.Client, file, filename)
			if err != nil {
				return err
			}
			reqFileData = append(reqFileData, []interface{}{
				[]interface{}{urlStr},
				filename,
			})
		}
	}

	// Re-execute activity before generation (as per python client)
	if len(options.Files) > 0 {
		activityPayload := RPCData{
			RPCID:   GRPCBardActivity,
			Payload: "[[[\"bard_activity_enabled\"]]]",
		}
		if err := c.BatchExecute([]RPCData{activityPayload}); err != nil {
			return err
		}
	}

	messageContent := []interface{}{
		prompt,
		0,
		nil,
		reqFileData,
		nil,
		nil,
		0,
	}

	chatMetadata := make([]interface{}, 10)
	if options.Chat != nil {
		for i, v := range options.Chat.Metadata {
			if i < 10 {
				if v == "" {
					chatMetadata[i] = nil
				} else {
					chatMetadata[i] = v
				}
			}
		}
	} else {
		for i := 0; i < 10; i++ {
			if i < 3 {
				chatMetadata[i] = ""
			} else {
				chatMetadata[i] = nil
			}
		}
		chatMetadata[9] = ""
	}

	innerReqList := make([]interface{}, 69)
	innerReqList[0] = messageContent
	innerReqList[2] = chatMetadata
	innerReqList[7] = 1 // Enable Snapshot Streaming

	if options.Gem != nil {
		innerReqList[19] = options.Gem.ID
	}

	innerReqJSON, _ := json.Marshal(innerReqList)
	reqJSON, _ := json.Marshal([]interface{}{nil, string(innerReqJSON)})

	form := url.Values{}
	form.Set("at", c.AccessToken)
	form.Set("f.req", string(reqJSON))

	reqURL, _ := url.Parse(EndpointGenerate)
	q := reqURL.Query()
	q.Set("_reqid", strconv.Itoa(reqID))
	q.Set("rt", "c")
	if c.BuildLabel != "" {
		q.Set("bl", c.BuildLabel)
	}
	if c.SessionID != "" {
		q.Set("f.sid", c.SessionID)
	}
	reqURL.RawQuery = q.Encode()

	req, err := http.NewRequest("POST", reqURL.String(), strings.NewReader(form.Encode()))
	if err != nil {
		return err
	}

	for k, v := range HeadersGemini {
		req.Header.Set(k, v)
	}
	for k, v := range options.Model.Header {
		req.Header.Set(k, v)
	}

	resp, err := c.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return fmt.Errorf("failed to generate content, status: %s", resp.Status)
	}

	if c.Client.Jar != nil {
		u, _ := url.Parse(EndpointGoogle)
		c.Cookies = c.Client.Jar.Cookies(u)
	}

	reader := bufio.NewReader(resp.Body)

	sessionState := struct {
		lastTexts    map[string]string
		lastThoughts map[string]string
	}{
		lastTexts:    make(map[string]string),
		lastThoughts: make(map[string]string),
	}

	buffer := ""
	buf := make([]byte, 1024)

	for {
		n, err := reader.Read(buf)
		if n > 0 {
			chunk := string(buf[:n])
			buffer += chunk

			if strings.HasPrefix(buffer, ")]}'") {
				buffer = buffer[4:]
				buffer = strings.TrimLeft(buffer, " \t\n\r")
			}

			frames, remaining := ParseResponseByFrame(buffer)
			buffer = remaining

			for _, frame := range frames {
				outputs, err := processFrame(frame, options.Chat, sessionState.lastTexts, sessionState.lastThoughts, c.Proxy)
				if err != nil {
					continue
				}
				for _, out := range outputs {
					outChan <- out
				}
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
	}

	if buffer != "" {
		frames, _ := ParseResponseByFrame(buffer)
		for _, frame := range frames {
			outputs, _ := processFrame(frame, options.Chat, sessionState.lastTexts, sessionState.lastThoughts, c.Proxy)
			for _, out := range outputs {
				outChan <- out
			}
		}
	}

	return nil
}

func processFrame(frame interface{}, chat *ChatSession, lastTexts, lastThoughts map[string]string, proxy string) ([]ModelOutput, error) {
	innerJSONStr := GetNestedValue(frame, []interface{}{2})
	str, ok := innerJSONStr.(string)
	if !ok {
		return nil, nil
	}

	var partJSON []interface{}
	if err := json.Unmarshal([]byte(str), &partJSON); err != nil {
		return nil, err
	}

	mData := GetNestedValue(partJSON, []interface{}{1})
	if mDataSlice, ok := mData.([]interface{}); ok && chat != nil {
		newMeta := make([]string, 10)
		for i, v := range mDataSlice {
			if i < 10 {
				if s, ok := v.(string); ok {
					newMeta[i] = s
				}
			}
		}
		chat.Metadata = newMeta
	}

	contextStr := GetNestedValue(partJSON, []interface{}{25})
	if s, ok := contextStr.(string); ok && chat != nil {
		if len(chat.Metadata) >= 10 {
			chat.Metadata[9] = s
		}
	}

	candidatesList := GetNestedValue(partJSON, []interface{}{4})
	candidatesListSlice, ok := candidatesList.([]interface{})
	if !ok {
		return nil, nil
	}

	var outputCandidates []Candidate

	for i, candidateData := range candidatesListSlice {
		rcid, _ := GetNestedValue(candidateData, []interface{}{0}).(string)
		if rcid == "" {
			continue
		}
		if chat != nil {
			chat.RCID = rcid
		}

		text, _ := GetNestedValue(candidateData, []interface{}{1, 0}).(string)
		thoughts, _ := GetNestedValue(candidateData, []interface{}{37, 0, 0}).(string)

		var webImages []WebImage
		webImgData := GetNestedValue(candidateData, []interface{}{12, 1})
		if list, ok := webImgData.([]interface{}); ok {
			for _, item := range list {
				url, _ := GetNestedValue(item, []interface{}{0, 0, 0}).(string)
				if url != "" {
					title, _ := GetNestedValue(item, []interface{}{7, 0}).(string)
					alt, _ := GetNestedValue(item, []interface{}{0, 4}).(string)
					webImages = append(webImages, WebImage{Image: Image{URL: url, Title: title, Alt: alt, Proxy: proxy}})
				}
			}
		}

		var generatedImages []GeneratedImage
		genImgData := GetNestedValue(candidateData, []interface{}{12, 7, 0})
		if list, ok := genImgData.([]interface{}); ok {
			for _, item := range list {
				url, _ := GetNestedValue(item, []interface{}{0, 3, 3}).(string)
				if url != "" {
					imgNum, _ := GetNestedValue(item, []interface{}{3, 6}).(float64)
					title := "[Generated Image]"
					if imgNum != 0 {
						title = fmt.Sprintf("[Generated Image %.0f]", imgNum)
					}
					alt, _ := GetNestedValue(item, []interface{}{3, 5, 0}).(string)
					generatedImages = append(generatedImages, GeneratedImage{
						Image: Image{URL: url, Title: title, Alt: alt, Proxy: proxy},
					})
				}
			}
		}

		lastSentText := lastTexts[rcid]
		if lastSentText == "" {
			lastSentText = lastTexts[fmt.Sprintf("idx_%d", i)]
		}

		isFinal := false
		if _, ok := GetNestedValue(candidateData, []interface{}{2}).([]interface{}); ok {
			isFinal = true
		} else {
			status, _ := GetNestedValue(candidateData, []interface{}{8, 0}).(float64)
			if status == 2 {
				isFinal = true
			}
		}

		textDelta, newFullText := GetDeltaByFPLen(text, lastSentText, isFinal)

		lastSentThought := lastThoughts[rcid]
		if lastSentThought == "" {
			lastSentThought = lastThoughts[fmt.Sprintf("idx_%d", i)]
		}

		thoughtsDelta := ""
		newFullThought := ""
		if thoughts != "" {
			thoughtsDelta, newFullThought = GetDeltaByFPLen(thoughts, lastSentThought, isFinal)
		}

		lastTexts[rcid] = newFullText
		lastTexts[fmt.Sprintf("idx_%d", i)] = newFullText
		lastThoughts[rcid] = newFullThought
		lastThoughts[fmt.Sprintf("idx_%d", i)] = newFullThought

		outputCandidates = append(outputCandidates, Candidate{
			RCID: rcid,
			Text: newFullText,
			TextDelta: textDelta,
			Thoughts: newFullThought,
			ThoughtsDelta: thoughtsDelta,
			WebImages: webImages,
			GeneratedImages: generatedImages,
		})
	}

	if len(outputCandidates) > 0 {
		var meta []string
		if mDataSlice, ok := mData.([]interface{}); ok {
			meta = make([]string, len(mDataSlice))
			for i, v := range mDataSlice {
				if s, ok := v.(string); ok {
					meta[i] = s
				}
			}
		}
		return []ModelOutput{{
			Metadata: meta,
			Candidates: outputCandidates,
			Chosen: 0,
		}}, nil
	}

	return nil, nil
}


type ChatSession struct {
	Client   *GeminiClient
	Metadata []string
	CID      string
	RID      string
	RCID     string
	Model    Model
	Gem      *Gem
}

func (c *GeminiClient) StartChat(opts ...Option) *ChatSession {
	options := generateOptions{
		Model: ModelUnspecified,
	}
	for _, o := range opts {
		o(&options)
	}

	return &ChatSession{
		Client: c,
		Model: options.Model,
		Gem: options.Gem,
		Metadata: make([]string, 10),
	}
}

func (s *ChatSession) SendMessage(prompt string, opts ...Option) (ModelOutput, error) {
    newOpts := []Option{
        WithModel(s.Model),
        WithChat(s),
    }
    if s.Gem != nil {
        newOpts = append(newOpts, WithGem(s.Gem))
    }
    newOpts = append(newOpts, opts...)

	output, err := s.Client.GenerateContent(prompt, newOpts...)
    if err == nil {
        if len(output.Metadata) >= 3 {
            s.CID = output.Metadata[0]
            s.RID = output.Metadata[1]
            s.RCID = output.Metadata[2]
            s.Metadata = output.Metadata
        }
    }
    return output, err
}

func (s *ChatSession) SendMessageStream(prompt string, outChan chan<- ModelOutput, opts ...Option) error {
    newOpts := []Option{
        WithModel(s.Model),
        WithChat(s),
    }
    if s.Gem != nil {
        newOpts = append(newOpts, WithGem(s.Gem))
    }
    newOpts = append(newOpts, opts...)

	return s.Client.GenerateContentStream(prompt, outChan, newOpts...)
}
